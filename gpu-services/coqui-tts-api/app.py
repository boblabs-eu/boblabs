"""CoquiTTS API — FastAPI service for text-to-speech with voice cloning.

Uses XTTS v2 via the coqui-ai TTS library. Supports:
  - Text-to-speech in 17 languages
  - Voice cloning from ~6 second reference audio
  - Adjustable speed and temperature
  - Long-form generation (auto-chunking)

Runs on GPU servers. Model loads on first request, unloads after idle timeout.
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

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from scipy.io.wavfile import write as wav_write

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("coqui-tts-api")

# ── Configuration ────────────────────────────────────

IDLE_UNLOAD_SEC = int(os.getenv("COQUI_IDLE_UNLOAD_SEC", "300"))
HOST = os.getenv("COQUI_HOST", "0.0.0.0")
PORT = int(os.getenv("COQUI_PORT", "3017"))
MAX_TEXT_LENGTH = int(os.getenv("COQUI_MAX_TEXT_LENGTH", "5000"))
SPEAKERS_DIR = Path(os.getenv("COQUI_SPEAKERS_DIR", "/speakers"))

# ── Global model state ───────────────────────────────

_tts = None
_model_lock = threading.Lock()
_last_used = 0.0
# R21 — remember which device we actually ended up on so the idle
# unloader knows whether to empty the CUDA cache. CPU-only hosts skip
# the cache flush (it's a no-op there but a noisy warning in some
# torch builds).
_device = "cpu"


def _detect_device() -> str:
    """Return 'cuda' if a usable GPU is present, else 'cpu'.

    The COQUI_DEVICE env var lets the operator force a choice
    (``cuda`` / ``cpu``) for tests and for hosts where ``torch.cuda``
    appears available but the runtime is broken.
    """
    forced = (os.environ.get("COQUI_DEVICE") or "").strip().lower()
    if forced in ("cpu", "cuda"):
        return forced
    try:
        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _ensure_model():
    """Load XTTS v2 onto the best available device.

    R21 — previously hardcoded ``.to("cuda")``, which crashed at first
    request on CPU-only hosts (the audit-context-building docs already
    flagged this as a deployment trap). Detect once on first load,
    remember the choice in ``_device``, and log it so operators have
    a clear breadcrumb when reading container logs.
    """
    global _tts, _last_used, _device
    with _model_lock:
        if _tts is not None:
            _last_used = time.time()
            return
        _device = _detect_device()
        logger.info("Loading XTTS v2 model on %s...", _device)
        from TTS.api import TTS

        _tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(_device)
        _last_used = time.time()
        logger.info("XTTS v2 model loaded on %s", _device)


def _unload_if_idle():
    """Background thread: unload model after idle timeout."""
    global _tts, _last_used
    while True:
        time.sleep(30)
        with _model_lock:
            if _tts is not None and (time.time() - _last_used) > IDLE_UNLOAD_SEC:
                logger.info("Idle timeout — unloading XTTS model")
                _tts = None
                # R21 — only flush the CUDA cache when we were actually
                # using it; on CPU-only hosts this would either be a
                # no-op or (depending on torch build) emit a warning.
                if _device == "cuda":
                    try:
                        torch.cuda.empty_cache()
                    except Exception:
                        logger.debug("torch.cuda.empty_cache failed", exc_info=True)


# ── Request / Response schemas ─────────────────────────


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH, description="Text to speak.")
    language: str = Field(
        default="en",
        description="Language code (en, es, fr, de, it, pt, pl, tr, ru, nl, cs, ar, zh-cn, ja, ko, hu, hi)",
    )
    speaker_wav: str | None = Field(
        default=None, description="Base64 WAV of reference speaker for voice cloning (~6s)"
    )
    speaker_name: str | None = Field(
        default=None, description="Name of a pre-saved speaker in /speakers (without extension)"
    )
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    temperature: float = Field(default=0.65, ge=0.1, le=1.0, description="Generation temperature")


class GenerateResponse(BaseModel):
    audio: str  # base64 WAV
    duration_s: float
    sample_rate: int


class SpeakerListResponse(BaseModel):
    speakers: list[str]


# ── App lifecycle ────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    SPEAKERS_DIR.mkdir(parents=True, exist_ok=True)
    t = threading.Thread(target=_unload_if_idle, daemon=True)
    t.start()
    logger.info("CoquiTTS API starting (speakers dir: %s)", SPEAKERS_DIR)
    yield
    logger.info("CoquiTTS API shutting down")


app = FastAPI(title="CoquiTTS API", version="1.0.0", lifespan=lifespan)


# ── Endpoints ────────────────────────────────────────


@app.get("/health")
async def health():
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else None
    return {
        "status": "ok",
        "service": "coqui-tts-api",
        "gpu_available": gpu_available,
        "gpu_name": gpu_name,
        "model_loaded": _tts is not None,
        "speakers_available": _list_speakers(),
    }


@app.get("/speakers", response_model=SpeakerListResponse)
async def list_speakers():
    return SpeakerListResponse(speakers=_list_speakers())


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    t0 = time.time()

    try:
        _ensure_model()
    except Exception as e:
        logger.error("Failed to load XTTS model: %s", e)
        raise HTTPException(status_code=503, detail=f"Failed to load model: {e}")

    # Resolve speaker reference audio
    speaker_wav_path = _resolve_speaker(req.speaker_wav, req.speaker_name)
    if speaker_wav_path is None:
        raise HTTPException(
            status_code=400,
            detail="Either 'speaker_wav' (base64) or 'speaker_name' (pre-saved) is required for XTTS v2",
        )

    try:
        with torch.no_grad():
            wav_list = _tts.tts(
                text=req.prompt,
                speaker_wav=str(speaker_wav_path),
                language=req.language,
                speed=req.speed,
                temperature=req.temperature,
            )

        audio = np.array(wav_list, dtype=np.float32)
        sample_rate = _tts.synthesizer.output_sample_rate
        duration_s = len(audio) / sample_rate

        audio_b64 = _encode_wav(audio, sample_rate)

        elapsed = time.time() - t0
        logger.info(
            "Generated %.1fs audio in %.1fs (lang=%s, prompt=%.60s...)",
            duration_s,
            elapsed,
            req.language,
            req.prompt,
        )

        return GenerateResponse(
            audio=audio_b64,
            duration_s=round(duration_s, 2),
            sample_rate=sample_rate,
        )

    except Exception as e:
        logger.error("Generation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")
    finally:
        # Clean up temp speaker file if we wrote one
        if req.speaker_wav and speaker_wav_path and speaker_wav_path.parent == Path("/tmp"):
            speaker_wav_path.unlink(missing_ok=True)


# ── Helpers ──────────────────────────────────────────


def _resolve_speaker(speaker_wav_b64: str | None, speaker_name: str | None) -> Path | None:
    """Resolve speaker reference audio to a file path."""
    if speaker_name:
        path = SPEAKERS_DIR / f"{speaker_name}.wav"
        if path.exists():
            return path
        # Also check without extension in case user included it
        path_direct = SPEAKERS_DIR / speaker_name
        if path_direct.exists():
            return path_direct
        raise HTTPException(
            status_code=404, detail=f"Speaker '{speaker_name}' not found in {SPEAKERS_DIR}"
        )

    if speaker_wav_b64:
        # Write to temp file — XTTS needs a file path
        tmp = Path(f"/tmp/speaker_{int(time.time() * 1000)}.wav")
        tmp.write_bytes(base64.b64decode(speaker_wav_b64))
        return tmp

    return None


def _list_speakers() -> list[str]:
    """List available pre-saved speaker names."""
    if not SPEAKERS_DIR.exists():
        return []
    return sorted(p.stem for p in SPEAKERS_DIR.glob("*.wav"))


def _encode_wav(audio: np.ndarray, sample_rate: int) -> str:
    """Encode numpy audio array to base64 WAV string."""
    buf = io.BytesIO()
    # Normalize to int16 range
    peak = np.abs(audio).max()
    if peak > 0:
        audio = audio / peak
    audio_int16 = (audio * 32767).astype(np.int16)
    wav_write(buf, sample_rate, audio_int16)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ── Main ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
