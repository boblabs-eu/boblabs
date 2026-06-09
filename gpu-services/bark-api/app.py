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
import hashlib
import io
import logging
import os
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import numpy as np
import torch

# A10 — pre-fix this monkey-patched torch.load **globally** to
# weights_only=False so Bark's checkpoint loader could keep working under
# PyTorch 2.6's tightened default. The side effect was that *every*
# torch.load anywhere in the process (including caller-provided model
# paths) unpickled with arbitrary code execution enabled. We now expose
# the relaxation only during the bark.preload_models() call via
# ``_allow_unsafe_torch_load``, restoring the safe default elsewhere.
_original_torch_load = torch.load


@contextmanager
def _allow_unsafe_torch_load():
    """Temporarily allow torch.load(weights_only=False) for code inside
    ``with`` (Bark preload path only). Outside this block the upstream
    PyTorch 2.6 default (weights_only=True) stays in force."""

    def _patched(*args, **kwargs):
        if "weights_only" not in kwargs:
            kwargs["weights_only"] = False
        return _original_torch_load(*args, **kwargs)

    torch.load = _patched
    try:
        yield
    finally:
        torch.load = _original_torch_load


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

# A10 — optional manifest of trusted checkpoint hashes. The operator
# drops a ``manifest.sha256`` file (one ``<sha256>  <filename>`` per
# line) next to the Bark HF cache; on startup we verify every listed
# file. Setting ``BARK_REQUIRE_MANIFEST=1`` makes the absence of the
# manifest a startup error (otherwise we warn and continue, preserving
# the old behaviour).
BARK_CHECKPOINT_DIR = os.getenv("BARK_CHECKPOINT_DIR", "")
BARK_REQUIRE_MANIFEST = os.getenv("BARK_REQUIRE_MANIFEST", "").lower() in ("1", "true", "yes")


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_bark_manifest() -> None:
    if not BARK_CHECKPOINT_DIR:
        return
    root = Path(BARK_CHECKPOINT_DIR)
    manifest = root / "manifest.sha256"
    if not manifest.exists():
        msg = f"A10: manifest.sha256 missing in {root}"
        if BARK_REQUIRE_MANIFEST:
            raise RuntimeError(msg)
        logger.warning("%s; skipping checksum verification", msg)
        return
    for line in manifest.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        expected, fname = parts[0].lower(), parts[1]
        target = root / fname
        if not target.is_file():
            raise RuntimeError(f"A10: manifest lists {fname} but file missing")
        actual = _sha256_of_file(target).lower()
        if actual != expected:
            raise RuntimeError(
                f"A10: checksum mismatch for {fname} — expected "
                f"{expected[:16]}..., got {actual[:16]}.... Refusing to start."
            )
        logger.info("A10: bark checkpoint %s verified", fname)


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

        # A10 — only relax torch.load's weights_only default for the
        # duration of Bark's checkpoint preload, not globally.
        with _allow_unsafe_torch_load():
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
    prompt: str = Field(
        ...,
        min_length=1,
        max_length=MAX_TEXT_LENGTH,
        description="Text to speak/sing. Use ♪ around lyrics for singing.",
    )
    speaker: str | None = Field(
        default=None, description="Speaker preset (e.g. 'v2/en_speaker_6') or None for random"
    )
    temperature: float = Field(
        default=0.7, ge=0.1, le=2.0, description="Generation temperature (higher=more variation)"
    )
    silence_padding_ms: int = Field(
        default=0, ge=0, le=2000, description="Silence padding at end (ms)"
    )


class GenerateResponse(BaseModel):
    audio: str  # base64 WAV
    duration_s: float
    sample_rate: int


# ── App lifecycle ────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A10 — verify operator-pinned checkpoint hashes (if configured)
    # before the first request can trigger _ensure_model().
    _verify_bark_manifest()
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
        from bark import SAMPLE_RATE, generate_audio

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
        logger.info(
            "Generated %.1fs audio in %.1fs (speaker=%s, prompt=%.60s...)",
            duration_s,
            elapsed,
            req.speaker,
            req.prompt,
        )

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

    sentences = re.split(r"(?<=[.!?;])\s+", text)

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
