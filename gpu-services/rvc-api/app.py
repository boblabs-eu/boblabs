"""RVC API — FastAPI service for voice conversion (Retrieval-based Voice Conversion).

Supports:
  - Voice conversion with pre-trained RVC models
  - Multiple pitch extraction methods (rmvpe, crepe, harvest, pm)
  - Pitch shifting
  - Index-based feature retrieval for natural timber

Runs on GPU servers. Models are loaded per-request from /models directory.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from scipy.io.wavfile import write as wav_write

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("rvc-api")

# ── Configuration ────────────────────────────────────

HOST = os.getenv("RVC_HOST", "0.0.0.0")
PORT = int(os.getenv("RVC_PORT", "3016"))
MODELS_DIR = Path(os.getenv("RVC_MODELS_DIR", "/models"))
IDLE_UNLOAD_SEC = int(os.getenv("RVC_IDLE_UNLOAD_SEC", "300"))
# D09 — TARGET_SR is no longer assumed; the model's `tgt_sr` (40k or 48k
# depending on the training config) is surfaced via the response so the
# caller can play / mix the audio with the correct sample rate. This
# constant is kept only as a fallback when the model dict lacks tgt_sr.
DEFAULT_FALLBACK_SR = 44100


# ── A10: optional model checksum gate ─────────────────────────────────
#
# torch.load() on a .pth uses pickle, which can execute arbitrary code at
# load time. If the operator commits the SHA-256 of each model to a
# sidecar file (``<model>.pth.sha256``), we refuse to load on mismatch.
# Absence of the sidecar disables the check (back-compat); enabling
# strict mode via ``RVC_REQUIRE_CHECKSUM=1`` instead refuses load when
# the sidecar is missing entirely.

RVC_REQUIRE_CHECKSUM = os.getenv("RVC_REQUIRE_CHECKSUM", "").lower() in ("1", "true", "yes")


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_model_checksum(model_path: Path) -> None:
    sidecar = model_path.with_suffix(model_path.suffix + ".sha256")
    if not sidecar.exists():
        if RVC_REQUIRE_CHECKSUM:
            raise RuntimeError(
                f"A10: model {model_path.name} has no .sha256 sidecar and "
                f"RVC_REQUIRE_CHECKSUM=1. Refusing to load untrusted pickle."
            )
        return
    expected = sidecar.read_text().split()[0].strip().lower() if sidecar.stat().st_size else ""
    if not expected:
        return
    actual = _sha256_of_file(model_path).lower()
    if actual != expected:
        raise RuntimeError(
            f"A10: checksum mismatch for {model_path.name} — expected "
            f"{expected[:16]}..., got {actual[:16]}.... Refusing to load."
        )
    logger.info("A10: model %s checksum verified", model_path.name)


# ── Global model state ───────────────────────────────

_loaded_models: dict[str, dict] = {}
_model_lock = threading.Lock()
_last_used = 0.0


def _list_available_models() -> list[str]:
    """List .pth model files in the models directory."""
    if not MODELS_DIR.exists():
        return []
    return [f.stem for f in MODELS_DIR.glob("*.pth")]


def _get_model(model_name: str):
    """Load or return cached RVC model."""
    global _last_used
    with _model_lock:
        if model_name in _loaded_models:
            _last_used = time.time()
            return _loaded_models[model_name]

        model_path = MODELS_DIR / f"{model_name}.pth"
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_name}")

        # A10 — verify SHA-256 before handing the path to torch.load
        # (which unpickles arbitrary objects).
        _verify_model_checksum(model_path)

        index_path = MODELS_DIR / f"{model_name}.index"

        logger.info("Loading RVC model: %s", model_name)

        from rvc_infer import load_model

        model_data = load_model(str(model_path), str(index_path) if index_path.exists() else None)

        _loaded_models[model_name] = model_data
        _last_used = time.time()
        logger.info("Model %s loaded", model_name)
        return model_data


def _unload_if_idle():
    """Background thread: unload all models after idle timeout."""
    global _last_used
    while True:
        time.sleep(30)
        with _model_lock:
            if _loaded_models and (time.time() - _last_used) > IDLE_UNLOAD_SEC:
                logger.info("Idle timeout — unloading %d model(s)", len(_loaded_models))
                _loaded_models.clear()
                torch.cuda.empty_cache()


# ── Request / Response schemas ───────────────────────


class InferRequest(BaseModel):
    audio: str = Field(..., description="Base64-encoded WAV input audio")
    model_name: str = Field(..., description="Name of the RVC model (without .pth extension)")
    pitch_shift: int = Field(
        default=0, ge=-24, le=24, description="Semitones to shift pitch (+12 = one octave up)"
    )
    f0_method: str = Field(
        default="rmvpe",
        pattern=r"^(rmvpe|crepe|harvest|pm)$",
        description="Pitch extraction method",
    )
    index_ratio: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Feature index ratio (0=disabled, 1=full retrieval)",
    )
    filter_radius: int = Field(
        default=3, ge=0, le=7, description="Median filter radius for pitch (reduces breathiness)"
    )
    rms_mix_rate: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Volume envelope mix (0=output only, 1=input envelope)",
    )
    protect: float = Field(
        default=0.33,
        ge=0.0,
        le=0.5,
        description="Protect voiceless consonants (higher=more protection)",
    )


class InferResponse(BaseModel):
    audio: str  # base64 WAV
    duration_s: float
    sample_rate: int
    model_name: str


class ModelsResponse(BaseModel):
    models: list[str]


# ── App lifecycle ────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_unload_if_idle, daemon=True)
    t.start()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("RVC API starting (models_dir: %s)", MODELS_DIR)
    yield
    logger.info("RVC API shutting down")


app = FastAPI(title="RVC API", version="1.0.0", lifespan=lifespan)


# ── Endpoints ────────────────────────────────────────


@app.get("/health")
async def health():
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else None
    return {
        "status": "ok",
        "service": "rvc-api",
        "gpu_available": gpu_available,
        "gpu_name": gpu_name,
        "models_loaded": list(_loaded_models.keys()),
        "models_available": _list_available_models(),
    }


@app.get("/models", response_model=ModelsResponse)
async def list_models():
    """List available voice models."""
    return ModelsResponse(models=_list_available_models())


@app.post("/infer", response_model=InferResponse)
async def infer(req: InferRequest):
    t0 = time.time()

    # Validate model exists
    available = _list_available_models()
    if req.model_name not in available:
        raise HTTPException(
            status_code=404, detail=f"Model '{req.model_name}' not found. Available: {available}"
        )

    try:
        model_data = _get_model(req.model_name)
    except Exception as e:
        logger.error("Failed to load model %s: %s", req.model_name, e)
        raise HTTPException(status_code=503, detail=f"Failed to load model: {e}")

    try:
        # Decode input audio
        raw = base64.b64decode(req.audio)
        import soundfile as sf

        input_buf = io.BytesIO(raw)
        input_audio, input_sr = sf.read(input_buf)

        # Run inference
        from rvc_infer import infer as rvc_infer

        output_audio = rvc_infer(
            model_data=model_data,
            audio=input_audio,
            sr=input_sr,
            f0_up_key=req.pitch_shift,
            f0_method=req.f0_method,
            index_ratio=req.index_ratio,
            filter_radius=req.filter_radius,
            rms_mix_rate=req.rms_mix_rate,
            protect=req.protect,
        )

        # D09 — use the model's native target sample rate (typically
        # 40000 or 48000 depending on the training config). Previously
        # this hardcoded 44100 which produced wrong pitch/duration on
        # any model that wasn't sampled at exactly 44.1 kHz.
        tgt_sr = int(model_data.get("tgt_sr") or DEFAULT_FALLBACK_SR)

        duration_s = len(output_audio) / tgt_sr

        # Encode output to WAV base64
        audio_b64 = _encode_wav(output_audio, tgt_sr)

        elapsed = time.time() - t0
        logger.info(
            "Converted %.1fs audio in %.1fs (model=%s, pitch=%+d, f0=%s, sr=%d)",
            duration_s,
            elapsed,
            req.model_name,
            req.pitch_shift,
            req.f0_method,
            tgt_sr,
        )

        return InferResponse(
            audio=audio_b64,
            duration_s=round(duration_s, 2),
            sample_rate=tgt_sr,
            model_name=req.model_name,
        )

    except Exception as e:
        logger.error("Inference failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Inference failed: {e}")


# ── Audio helpers ────────────────────────────────────


def _encode_wav(audio: np.ndarray, sample_rate: int) -> str:
    """Encode numpy audio array to base64 WAV string."""
    buf = io.BytesIO()
    if audio.dtype == np.float32 or audio.dtype == np.float64:
        audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    else:
        audio_int16 = audio.astype(np.int16)
    wav_write(buf, sample_rate, audio_int16)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ── Main ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
