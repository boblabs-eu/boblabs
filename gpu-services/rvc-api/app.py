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
import io
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

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
TARGET_SR = 44100

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
    pitch_shift: int = Field(default=0, ge=-24, le=24, description="Semitones to shift pitch (+12 = one octave up)")
    f0_method: str = Field(default="rmvpe", pattern=r"^(rmvpe|crepe|harvest|pm)$",
                           description="Pitch extraction method")
    index_ratio: float = Field(default=0.75, ge=0.0, le=1.0,
                               description="Feature index ratio (0=disabled, 1=full retrieval)")
    filter_radius: int = Field(default=3, ge=0, le=7,
                               description="Median filter radius for pitch (reduces breathiness)")
    rms_mix_rate: float = Field(default=0.25, ge=0.0, le=1.0,
                                description="Volume envelope mix (0=output only, 1=input envelope)")
    protect: float = Field(default=0.33, ge=0.0, le=0.5,
                           description="Protect voiceless consonants (higher=more protection)")


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
            status_code=404,
            detail=f"Model '{req.model_name}' not found. Available: {available}"
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

        duration_s = len(output_audio) / TARGET_SR

        # Encode output to WAV base64
        audio_b64 = _encode_wav(output_audio, TARGET_SR)

        elapsed = time.time() - t0
        logger.info("Converted %.1fs audio in %.1fs (model=%s, pitch=%+d, f0=%s)",
                     duration_s, elapsed, req.model_name, req.pitch_shift, req.f0_method)

        return InferResponse(
            audio=audio_b64,
            duration_s=round(duration_s, 2),
            sample_rate=TARGET_SR,
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
