"""Bob Manager — Speech-to-text pipeline (faster-whisper).

Wraps the stt-api FastAPI service behind the MediaPipeline abstraction.

Unlike other media pipelines that produce audio/image, STT produces text
output (transcripts). The pipeline returns the transcript as the media_url
field (plain text) with segments in extra_outputs.

API contract (gpu-services/stt-api):
    POST /transcribe  → TranscribeResponse (text, segments, language, duration, model)
    GET  /health      → {status, gpu_available, model_loaded, ...}
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.services.pipelines.base import MediaPipeline, PipelineResult

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=10.0, read=1800.0, write=30.0, pool=10.0)


class STTPipeline(MediaPipeline):
    """Speech-to-text pipeline using faster-whisper."""

    async def generate(self, params: dict) -> PipelineResult:
        """Send audio to stt-api /transcribe endpoint."""
        clean = self.validate_params(params)

        audio_bytes = clean.pop("_audio_bytes", None)
        filename = clean.pop("_filename", "audio.wav")

        if not audio_bytes:
            return PipelineResult(
                success=False,
                error="No audio data provided. Supply input_file in params.",
                params_used=clean,
            )

        try:
            files = {"file": (filename, audio_bytes)}
            form_data = {}
            if clean.get("language"):
                form_data["language"] = clean["language"]
            if clean.get("task"):
                form_data["task"] = clean["task"]
            if clean.get("model"):
                # stt-api expects the raw faster-whisper identifier (e.g. "large-v3-turbo")
                form_data["model_size"] = clean["model"]

            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{self.base_url}/transcribe",
                    files=files,
                    data=form_data,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            msg = f"STT HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            logger.error(msg)
            return PipelineResult(success=False, error=msg, params_used=clean)
        except Exception as exc:
            msg = f"STT request failed: {exc}"
            logger.error(msg)
            return PipelineResult(success=False, error=msg, params_used=clean)

        transcript = data.get("text", "")
        segments = data.get("segments", [])
        language = data.get("language", "unknown")
        duration = data.get("duration", 0.0)

        return PipelineResult(
            success=True,
            media_type="text",
            media_url="",  # transcript is in raw, not base64
            duration_s=duration,
            params_used=clean,
            raw=data,
            extra_outputs={},
        )

    def validate_params(self, params: dict) -> dict:
        """Validate STT parameters."""
        out: dict = {}

        task = str(params.get("task", "transcribe")).strip()
        if task not in ("transcribe", "translate"):
            task = "transcribe"
        out["task"] = task

        language = params.get("language")
        if language:
            out["language"] = str(language).strip()[:10]

        # Optional model override (e.g. "large-v3-turbo" or "whisper-large-v3-turbo").
        # The "whisper-" prefix is the model_identifier convention surfaced via
        # /list_models; strip it for the upstream stt-api which expects the raw
        # faster-whisper name.
        model = params.get("model") or params.get("model_size")
        if model:
            raw = str(model).strip()
            if raw.startswith("whisper-"):
                raw = raw[len("whisper-"):]
            if raw:
                out["model"] = raw[:64]

        # Carry through internal audio bytes (set by build_tool_params)
        if "_audio_bytes" in params:
            out["_audio_bytes"] = params["_audio_bytes"]
        if "_filename" in params:
            out["_filename"] = params["_filename"]

        return out

    def system_prompt(self) -> str:
        return (
            "You are an STT parameter generator. The speech_to_text tool "
            "transcribes audio files to text.\n\n"
            "Parameters:\n"
            "- input_file (str, required): path to audio file in workspace\n"
            "- language (str, optional): ISO language code (auto-detect if omitted)\n"
            "- task (str): 'transcribe' (default) or 'translate' (to English)\n"
            "- model (str, optional): whisper variant — e.g. 'whisper-large-v3-turbo' "
            "for ~8× speedup. Omit to use the server default.\n\n"
            "Reply with ONLY valid JSON."
        )

    def build_tool_params(self, prompt: str, extra: dict) -> dict:
        """Build STT params. The prompt is unused; input_file is required."""
        params: dict[str, Any] = {}
        if extra.get("language"):
            params["language"] = extra["language"]
        if extra.get("task"):
            params["task"] = extra["task"]
        if extra.get("model"):
            params["model"] = extra["model"]

        # Audio bytes are injected by the tool executor after reading input_file
        if extra.get("_audio_bytes"):
            params["_audio_bytes"] = extra["_audio_bytes"]
        if extra.get("_filename"):
            params["_filename"] = extra["_filename"]

        return params

    def tool_description(self) -> str:
        return (
            "stt — speech-to-text transcription (faster-whisper). "
            "Transcribes audio files to text with timestamps. "
            "params: input_file (required, workspace path), "
            "language (ISO code, auto-detect if omitted), "
            "task ('transcribe' or 'translate' to English), "
            "model (optional, e.g. 'whisper-large-v3-turbo' for ~8× faster transcription)"
        )

    def format_summary(self, params: dict) -> str:
        lang = params.get("language", "auto")
        task = params.get("task", "transcribe")
        return f"**Task**: {task} · **Language**: {lang}"

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False
