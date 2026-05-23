"""Bark API — FastAPI service for text-to-speech with music/singing.

Uses Suno's Bark model. Supports:
  - Text-to-speech with natural intonation
  - Singing (wrap lyrics in ♪ tokens)
  - Speaker presets for voice cloning
  - Long-form generation (auto-splits text)

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

import numpy as np
import torch

# PyTorch 2.6+ changed torch.load() default to weights_only=True,
# which breaks Bark's model checkpoint loading.  Patch it globally.
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    if "weights_only" not in kwargs:
        kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from scipy.io.wavfile import write as wav_write

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bark-api")

# ── Configuration ────────────────────────────────────

IDLE_UNLOAD_SEC = int(os.getenv("BARK_IDLE_UNLOAD_SEC", "300"))
HOST = os.getenv("BARK_HOST", "0.0.0.0")
PORT = int(os.getenv("BARK_PORT", "3015"))
MAX_TEXT_LENGTH = int(os.getenv("BARK_MAX_TEXT_LENGTH", "2000"))

# ── Global model state ───────────────────────────────

_model_loaded = False
_model_lock = threading.Lock()
_last_used = 0.0


def _ensure_model():
    """Preload Bark models into GPU memory."""
    global _model_loaded, _last_used
    with _model_lock:
        if _model_loaded:
            _last_used = time.time()
            return
        logger.info("Loading Bark models...")
        from bark import preload_models
        preload_models()
        _model_loaded = True
        _last_used = time.time()
        logger.info("Bark models loaded")


def _unload_if_idle():
    """Background thread: unload models after idle timeout."""
    global _model_loaded, _last_used
    while True:
        time.sleep(30)
        with _model_lock:
            if _model_loaded and (time.time() - _last_used) > IDLE_UNLOAD_SEC:
                logger.info("Idle timeout — clearing Bark model cache")
                torch.cuda.empty_cache()
                _model_loaded = False


# ── Request / Response schemas ───────────────────────

class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH,
                        description="Text to speak/sing. Use ♪ around lyrics for singing.")
    speaker: str | None = Field(default=None,
                                description="Speaker preset (e.g. 'v2/en_speaker_6') or None for random")
    temperature: float = Field(default=0.7, ge=0.1, le=2.0,
                               description="Generation temperature (higher=more variation)")
    silence_padding_ms: int = Field(default=0, ge=0, le=2000,
                                    description="Silence padding at end (ms)")


class GenerateResponse(BaseModel):
    audio: str  # base64 WAV
    duration_s: float
    sample_rate: int


# ── App lifecycle ────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_unload_if_idle, daemon=True)
    t.start()
    logger.info("Bark API starting (max text: %d chars)", MAX_TEXT_LENGTH)
    yield
    logger.info("Bark API shutting down")


app = FastAPI(title="Bark API", version="1.0.0", lifespan=lifespan)


# ── Endpoints ────────────────────────────────────────

@app.get("/health")
async def health():
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else None
    return {
        "status": "ok",
        "service": "bark-api",
        "gpu_available": gpu_available,
        "gpu_name": gpu_name,
        "model_loaded": _model_loaded,
    }


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    t0 = time.time()

    try:
        _ensure_model()
    except Exception as e:
        logger.error("Failed to load Bark models: %s", e)
        raise HTTPException(status_code=503, detail=f"Failed to load models: {e}")

    try:
        from bark import generate_audio, SAMPLE_RATE

        # For long text, split into sentences and generate each
        segments = _split_text(req.prompt)
        all_audio = []

        for i, segment in enumerate(segments):
            logger.info("Generating segment %d/%d (len=%d)", i + 1, len(segments), len(segment))
            with torch.no_grad():
                audio_array = generate_audio(
                    segment,
                    history_prompt=req.speaker,
                    text_temp=req.temperature,
                    waveform_temp=req.temperature,
                )
            all_audio.append(audio_array)

        # Concatenate segments
        if len(all_audio) > 1:
            full_audio = np.concatenate(all_audio)
        else:
            full_audio = all_audio[0]

        # Add silence padding if requested
        if req.silence_padding_ms > 0:
            silence = np.zeros(int(SAMPLE_RATE * req.silence_padding_ms / 1000))
            full_audio = np.concatenate([full_audio, silence])

        duration_s = len(full_audio) / SAMPLE_RATE

        # Encode to WAV base64
        audio_b64 = _encode_wav(full_audio, SAMPLE_RATE)

        elapsed = time.time() - t0
        logger.info("Generated %.1fs audio in %.1fs (speaker=%s, prompt=%.60s...)",
                     duration_s, elapsed, req.speaker, req.prompt)

        return GenerateResponse(
            audio=audio_b64,
            duration_s=round(duration_s, 2),
            sample_rate=SAMPLE_RATE,
        )

    except Exception as e:
        logger.error("Generation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")


# ── Text helpers ─────────────────────────────────────

def _split_text(text: str, max_chars: int = 250) -> list[str]:
    """Split long text into segments at sentence boundaries.
    
    Bark works best with short segments (~13s each, <250 chars).
    """
    if len(text) <= max_chars:
        return [text]

    segments = []
    current = ""
    # Split on sentence-ending punctuation
    import re
    sentences = re.split(r'(?<=[.!?;])\s+', text)

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip() if current else sentence
        else:
            if current:
                segments.append(current)
            # If a single sentence exceeds max_chars, include it as-is
            current = sentence

    if current:
        segments.append(current)

    return segments if segments else [text]


# ── Audio helpers ────────────────────────────────────

def _encode_wav(audio: np.ndarray, sample_rate: int) -> str:
    """Encode numpy audio array to base64 WAV string."""
    buf = io.BytesIO()
    # Normalize to int16
    audio_int16 = (audio * 32767).astype(np.int16)
    wav_write(buf, sample_rate, audio_int16)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ── Main ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
