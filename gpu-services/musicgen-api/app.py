"""MusicGen API — FastAPI service for text-to-music generation.

Uses Meta's AudioCraft library. Supports:
  - Text-to-music generation
  - Melody conditioning (musicgen-melody model)
  - Audio continuation (extend a clip with a new prompt)

Runs on GPU servers. Models load on first request, unload after idle timeout.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

import torch
import torchaudio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("musicgen-api")

# ── Configuration ────────────────────────────────────

MODEL_SIZE = os.getenv("MUSICGEN_MODEL", "medium")  # small|medium|large|melody
IDLE_UNLOAD_SEC = int(os.getenv("MUSICGEN_IDLE_UNLOAD_SEC", "300"))  # 5 min
MAX_DURATION_SEC = float(os.getenv("MUSICGEN_MAX_DURATION_SEC", "30"))
HOST = os.getenv("MUSICGEN_HOST", "0.0.0.0")
PORT = int(os.getenv("MUSICGEN_PORT", "3014"))

# ── Global model state ───────────────────────────────

_model = None
_model_name = None
_model_lock = threading.Lock()
_last_used = 0.0


def _get_model(name: str):
    """Load or return cached AudioCraft MusicGen model."""
    global _model, _model_name, _last_used
    with _model_lock:
        if _model is not None and _model_name == name:
            _last_used = time.time()
            return _model
        # Unload previous model if different
        if _model is not None:
            logger.info("Unloading previous model %s", _model_name)
            del _model
            _model = None
            torch.cuda.empty_cache()

        logger.info("Loading MusicGen model: %s", name)
        from audiocraft.models import MusicGen
        _model = MusicGen.get_pretrained(f"facebook/musicgen-{name}")
        _model_name = name
        _last_used = time.time()
        logger.info("Model %s loaded (device: %s)", name, next(_model.lm.parameters()).device)
        return _model


def _unload_if_idle():
    """Background thread: unload model after idle timeout."""
    global _model, _model_name, _last_used
    while True:
        time.sleep(30)
        with _model_lock:
            if _model is not None and (time.time() - _last_used) > IDLE_UNLOAD_SEC:
                logger.info("Idle timeout — unloading model %s", _model_name)
                del _model
                _model = None
                _model_name = None
                torch.cuda.empty_cache()


# ── Request / Response schemas ───────────────────────

class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1000, description="Text description of the music to generate")
    duration: float = Field(default=15.0, ge=1.0, le=MAX_DURATION_SEC, description="Duration in seconds")
    model: str = Field(default=MODEL_SIZE, pattern=r"^(small|medium|large|melody)$", description="Model variant")
    temperature: float = Field(default=1.0, ge=0.1, le=2.0)
    top_k: int = Field(default=250, ge=0, le=1000)
    top_p: float = Field(default=0.0, ge=0.0, le=1.0)
    continuation_audio: Optional[str] = Field(default=None, description="Base64 WAV to continue from")
    melody_audio: Optional[str] = Field(default=None, description="Base64 WAV for melody conditioning (melody model only)")
    # D10 — the prior `sample_rate` request field was declared but
    # never wired into the encoder (the response always carried the
    # model's native rate, typically 32 000 Hz). Field removed to
    # match actual behavior; callers that need resampling do it
    # client-side. Response.sample_rate still carries the rate.


class GenerateResponse(BaseModel):
    audio: str  # base64 WAV
    duration_s: float
    sample_rate: int
    model: str


# ── App lifecycle ────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start idle-unload background thread
    t = threading.Thread(target=_unload_if_idle, daemon=True)
    t.start()
    logger.info("MusicGen API starting (default model: %s, max duration: %ss)", MODEL_SIZE, MAX_DURATION_SEC)
    yield
    logger.info("MusicGen API shutting down")


app = FastAPI(title="MusicGen API", version="1.0.0", lifespan=lifespan)


# ── Endpoints ────────────────────────────────────────

@app.get("/health")
async def health():
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else None
    return {
        "status": "ok",
        "service": "musicgen-api",
        "gpu_available": gpu_available,
        "gpu_name": gpu_name,
        "model_loaded": _model_name,
        "default_model": MODEL_SIZE,
    }


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    t0 = time.time()

    try:
        model = _get_model(req.model)
    except Exception as e:
        logger.error("Failed to load model %s: %s", req.model, e)
        raise HTTPException(status_code=503, detail=f"Failed to load model: {e}")

    # Configure generation
    model.set_generation_params(
        duration=req.duration,
        temperature=req.temperature,
        top_k=req.top_k,
        top_p=req.top_p,
    )

    try:
        # Decode optional audio inputs
        melody_wav = None
        continuation_wav = None

        if req.melody_audio and req.model == "melody":
            melody_wav = _decode_audio(req.melody_audio, model.sample_rate)

        if req.continuation_audio:
            continuation_wav = _decode_audio(req.continuation_audio, model.sample_rate)

        # Generate
        with torch.no_grad():
            if continuation_wav is not None:
                wav = model.generate_continuation(
                    continuation_wav,
                    model.sample_rate,
                    [req.prompt],
                    progress=False,
                )
            elif melody_wav is not None:
                wav = model.generate_with_chroma(
                    [req.prompt],
                    melody_wav,
                    model.sample_rate,
                    progress=False,
                )
            else:
                wav = model.generate([req.prompt], progress=False)

        # wav shape: [batch, channels, samples]
        wav = wav[0]  # first (only) batch item
        actual_sr = model.sample_rate
        duration_s = wav.shape[-1] / actual_sr

        # Encode to WAV base64
        audio_b64 = _encode_wav(wav, actual_sr)

        elapsed = time.time() - t0
        logger.info("Generated %.1fs audio in %.1fs (model=%s, prompt=%.60s...)", duration_s, elapsed, req.model, req.prompt)

        return GenerateResponse(
            audio=audio_b64,
            duration_s=round(duration_s, 2),
            sample_rate=actual_sr,
            model=req.model,
        )

    except Exception as e:
        logger.error("Generation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")


# ── Audio helpers ────────────────────────────────────

def _decode_audio(b64_data: str, target_sr: int) -> torch.Tensor:
    """Decode base64 WAV/MP3 to tensor, resample if needed."""
    raw = base64.b64decode(b64_data)
    buf = io.BytesIO(raw)
    wav, sr = torchaudio.load(buf)
    if sr != target_sr:
        wav = torchaudio.functional.resample(wav, sr, target_sr)
    # Ensure shape [batch, channels, samples]
    if wav.dim() == 1:
        wav = wav.unsqueeze(0)
    if wav.dim() == 2:
        wav = wav.unsqueeze(0)
    return wav.cuda() if torch.cuda.is_available() else wav


def _encode_wav(wav: torch.Tensor, sample_rate: int) -> str:
    """Encode tensor to base64 WAV string."""
    wav_cpu = wav.cpu()
    if wav_cpu.dim() == 1:
        wav_cpu = wav_cpu.unsqueeze(0)
    buf = io.BytesIO()
    torchaudio.save(buf, wav_cpu, sample_rate, format="wav")
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ── Main ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
