"""STT API — FastAPI service for speech-to-text transcription.

Uses faster-whisper (CTranslate2 backend) for efficient GPU-accelerated
speech recognition. Supports:
  - Audio file transcription
  - Language auto-detection or forced language
  - Translation to English
  - Segment-level timestamps

Runs on GPU servers. Model loads on first request, unloads after idle timeout.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

import torch
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("stt-api")

# ── Configuration ────────────────────────────────────

MODEL_SIZE = os.getenv("STT_MODEL_SIZE", "large-v3")
IDLE_UNLOAD_SEC = int(os.getenv("STT_IDLE_UNLOAD_SEC", "300"))
COMPUTE_TYPE = os.getenv("STT_COMPUTE_TYPE", "float16")  # float16, int8_float16, int8
MAX_FILE_SIZE_MB = int(os.getenv("STT_MAX_FILE_SIZE_MB", "500"))
HOST = os.getenv("STT_HOST", "0.0.0.0")
PORT = int(os.getenv("STT_PORT", "7865"))

# Comma-separated allowlist of faster-whisper model identifiers the service is
# willing to load. Per-request `model_size` form param is validated against this
# list. The default model (above) is auto-prepended if missing.
_AVAILABLE_RAW = os.getenv("STT_AVAILABLE_MODELS", "large-v3,large-v3-turbo")
AVAILABLE_MODELS: list[str] = [m.strip() for m in _AVAILABLE_RAW.split(",") if m.strip()]
if MODEL_SIZE not in AVAILABLE_MODELS:
    AVAILABLE_MODELS = [MODEL_SIZE, *AVAILABLE_MODELS]

# ── Global model state ───────────────────────────────

_model = None
_model_name: str | None = None
_model_lock = threading.Lock()
_last_used = 0.0
_active_requests = 0
_active_lock = threading.Lock()


def _get_model(name: str):
    """Load or return cached faster-whisper model."""
    global _model, _model_name, _last_used
    with _model_lock:
        if _model is not None and _model_name == name:
            _last_used = time.time()
            return _model

        if _model is not None:
            logger.info("Unloading previous model %s", _model_name)
            del _model
            _model = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        logger.info("Loading faster-whisper model: %s (compute=%s)", name, COMPUTE_TYPE)
        from faster_whisper import WhisperModel

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = WhisperModel(
            name,
            device=device,
            compute_type=COMPUTE_TYPE if device == "cuda" else "int8",
        )
        _model_name = name
        _last_used = time.time()
        logger.info("Model %s loaded on %s", name, device)
        return _model


def _unload_if_idle():
    """Background thread: unload model after idle timeout."""
    global _model, _model_name, _last_used
    while True:
        time.sleep(30)
        with _model_lock:
            with _active_lock:
                busy = _active_requests > 0
            if _model is not None and not busy and (time.time() - _last_used) > IDLE_UNLOAD_SEC:
                logger.info("Idle timeout — unloading model %s", _model_name)
                del _model
                _model = None
                _model_name = None
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()


# ── Response schemas ─────────────────────────────────


class Segment(BaseModel):
    start: float
    end: float
    text: str


class TranscribeResponse(BaseModel):
    text: str
    segments: list[Segment]
    language: str
    duration: float
    model: str


# ── App lifecycle ────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_unload_if_idle, daemon=True)
    t.start()
    logger.info(
        "STT API starting (model: %s, compute: %s, max file: %sMB)",
        MODEL_SIZE,
        COMPUTE_TYPE,
        MAX_FILE_SIZE_MB,
    )
    yield
    logger.info("STT API shutting down")


app = FastAPI(title="STT API", version="1.0.0", lifespan=lifespan)


# ── Endpoints ────────────────────────────────────────


@app.get("/health")
async def health():
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else None
    return {
        "status": "ok",
        "service": "stt-api",
        "gpu_available": gpu_available,
        "gpu_name": gpu_name,
        "model_loaded": _model_name,
        "default_model": MODEL_SIZE,
        "available_models": AVAILABLE_MODELS,
    }


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    request: Request,
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    task: Optional[str] = Form("transcribe"),
    model_size: Optional[str] = Form(None),
):
    """Transcribe an audio file to text.

    Args:
        file: Audio file (mp3, wav, m4a, flac, ogg, etc.)
        language: ISO language code (auto-detect if omitted)
        task: 'transcribe' or 'translate' (translate to English)
        model_size: Override model size (default from env)
    """
    if task not in ("transcribe", "translate"):
        raise HTTPException(400, "task must be 'transcribe' or 'translate'")

    # R20 — refuse oversized uploads BEFORE pulling the whole body into
    # memory. Two layers:
    #   1) Honour the client-declared Content-Length when present
    #      (cheapest path, rejects multi-GB uploads before any byte
    #      reaches the worker).
    #   2) Stream the body in 1 MiB chunks; abort as soon as the
    #      accumulated size exceeds the cap.
    # Previously ``await file.read()`` slurped the entire body, so a
    # client uploading 5 GB held 5 GB in worker RAM before the
    # if-too-large branch fired.
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    declared_len = request.headers.get("content-length")
    if declared_len:
        try:
            if int(declared_len) > max_bytes:
                raise HTTPException(
                    413,
                    f"File too large (Content-Length={int(declared_len) / (1024 * 1024):.1f}MB). "
                    f"Max: {MAX_FILE_SIZE_MB}MB",
                )
        except ValueError:
            pass

    chunks: list[bytes] = []
    total = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                413,
                f"File too large (>{total / (1024 * 1024):.1f}MB). Max: {MAX_FILE_SIZE_MB}MB",
            )
        chunks.append(chunk)
    content = b"".join(chunks)

    model_name = model_size or MODEL_SIZE
    if model_name not in AVAILABLE_MODELS:
        raise HTTPException(
            400,
            f"model_size '{model_name}' not in allowlist {AVAILABLE_MODELS}. "
            f"Update STT_AVAILABLE_MODELS env to expose more models.",
        )

    try:
        model = _get_model(model_name)
    except Exception as e:
        logger.error("Failed to load model %s: %s", model_name, e)
        raise HTTPException(503, f"Failed to load model: {e}")

    with _active_lock:
        global _active_requests
        _active_requests += 1

    try:
        # Write to temp file (faster-whisper needs a file path)
        suffix = _safe_suffix(file.filename)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(content)
            tmp.flush()

            t0 = time.time()
            try:
                segments_iter, info = model.transcribe(
                    tmp.name,
                    language=language,
                    task=task,
                    beam_size=5,
                    vad_filter=True,
                )

                segments = []
                full_text_parts = []
                for seg in segments_iter:
                    segments.append(
                        Segment(
                            start=round(seg.start, 2),
                            end=round(seg.end, 2),
                            text=seg.text.strip(),
                        )
                    )
                    full_text_parts.append(seg.text.strip())

            except Exception as e:
                logger.exception("Transcription failed")
                raise HTTPException(500, f"Transcription failed: {e}")
    finally:
        with _active_lock:
            _active_requests -= 1
        global _last_used
        _last_used = time.time()

    elapsed = time.time() - t0
    full_text = " ".join(full_text_parts)
    detected_lang = info.language if info else "unknown"
    duration = info.duration if info else 0.0

    logger.info(
        "Transcribed %.1fs audio in %.1fs (%d segments, lang=%s, model=%s)",
        duration,
        elapsed,
        len(segments),
        detected_lang,
        model_name,
    )

    return TranscribeResponse(
        text=full_text,
        segments=segments,
        language=detected_lang,
        duration=round(duration, 2),
        model=model_name,
    )


def _safe_suffix(filename: str | None) -> str:
    """Extract a safe file suffix from filename, defaulting to .wav."""
    if not filename:
        return ".wav"
    allowed = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".mp4", ".aac"}
    dot = filename.rfind(".")
    if dot >= 0:
        ext = filename[dot:].lower()
        if ext in allowed:
            return ext
    return ".wav"


# ── Main ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, workers=1)
