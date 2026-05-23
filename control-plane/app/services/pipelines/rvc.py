"""Bob Manager — RVC voice conversion pipeline.

Wraps the rvc-api FastAPI service behind the MediaPipeline abstraction.

API contract (gpu-services/rvc-api):
    POST /infer   → InferResponse (audio: base64 WAV, duration_s, sample_rate, model_name)
    GET  /health  → {status, gpu_available, models_loaded, models_available, ...}
    GET  /models  → {models: [str]}
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.pipelines.base import MediaPipeline, PipelineResult

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────

DEFAULT_PARAMS: dict[str, Any] = {
    "pitch_shift": 0,
    "f0_method": "rmvpe",
    "index_ratio": 0.75,
    "filter_radius": 3,
    "rms_mix_rate": 0.25,
    "protect": 0.33,
}

_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)


class RVCPipeline(MediaPipeline):
    """RVC voice conversion pipeline (Retrieval-based Voice Conversion)."""

    async def generate(self, params: dict) -> PipelineResult:
        clean = self.validate_params(params)

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(f"{self.base_url}/infer", json=clean)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            msg = f"RVC HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            logger.error(msg)
            return PipelineResult(success=False, error=msg, params_used=clean)
        except Exception as exc:
            msg = f"RVC request failed: {exc}"
            logger.error(msg)
            return PipelineResult(success=False, error=msg, params_used=clean)

        return PipelineResult(
            success=True,
            media_type="audio",
            media_url=data.get("audio", ""),
            duration_s=data.get("duration_s", 0.0),
            params_used=clean,
            raw=data,
        )

    def validate_params(self, params: dict) -> dict:
        out: dict = {}

        # Audio is required (base64)
        audio = params.get("audio", "")
        if not audio:
            raise ValueError("Missing 'audio' — RVC requires base64-encoded input audio")
        out["audio"] = audio

        model_name = str(params.get("model_name", "")).strip()
        if not model_name:
            raise ValueError("Missing 'model_name' — specify which RVC voice model to use")
        out["model_name"] = model_name

        out["pitch_shift"] = _clamp(int(params.get("pitch_shift", DEFAULT_PARAMS["pitch_shift"])), -24, 24)

        f0 = str(params.get("f0_method", DEFAULT_PARAMS["f0_method"]))
        if f0 not in ("rmvpe", "crepe", "harvest", "pm"):
            f0 = "rmvpe"
        out["f0_method"] = f0

        out["index_ratio"] = _clamp(float(params.get("index_ratio", DEFAULT_PARAMS["index_ratio"])), 0.0, 1.0)
        out["filter_radius"] = _clamp(int(params.get("filter_radius", DEFAULT_PARAMS["filter_radius"])), 0, 7)
        out["rms_mix_rate"] = _clamp(float(params.get("rms_mix_rate", DEFAULT_PARAMS["rms_mix_rate"])), 0.0, 1.0)
        out["protect"] = _clamp(float(params.get("protect", DEFAULT_PARAMS["protect"])), 0.0, 0.5)

        return out

    def system_prompt(self) -> str:
        return (
            "You are an RVC parameter generator. Translate the user's voice conversion "
            "request into a JSON payload for the RVC inference API.\n\n"
            "Parameters:\n"
            "- audio (str): base64-encoded WAV input audio (required)\n"
            "- model_name (str): name of the RVC voice model (required)\n"
            "- pitch_shift (int): semitones -24 to +24 (default 0)\n"
            "- f0_method: rmvpe|crepe|harvest|pm (default rmvpe)\n"
            "- index_ratio (float): 0-1 (default 0.75)\n"
            "- filter_radius (int): 0-7 (default 3)\n"
            "- rms_mix_rate (float): 0-1 (default 0.25)\n"
            "- protect (float): 0-0.5 (default 0.33)\n\n"
            "Reply with ONLY valid JSON."
        )

    def build_tool_params(self, prompt: str, extra: dict) -> dict:
        params: dict = {}
        # RVC needs audio input — injected by handler as input_audio_b64
        if "input_audio_b64" in extra:
            params["audio"] = extra["input_audio_b64"]
        elif "audio" in extra:
            params["audio"] = extra["audio"]

        # model_name is required
        if "model_name" in extra:
            params["model_name"] = extra["model_name"]

        for key in ("pitch_shift", "f0_method", "index_ratio", "filter_radius",
                     "rms_mix_rate", "protect"):
            if key in extra:
                params[key] = extra[key]

        return params

    def tool_description(self) -> str:
        return (
            "rvc — voice conversion (Retrieval-based Voice Conversion). "
            "Converts the voice in an audio file to a target voice model. "
            "Requires input_file (workspace path to audio) and model_name. "
            "params: input_file (path), model_name, pitch_shift (-24 to +24 semitones), "
            "f0_method (rmvpe/crepe/harvest/pm), index_ratio, filter_radius, "
            "rms_mix_rate, protect"
        )

    def format_summary(self, params: dict) -> str:
        model = params.get("model_name", "unknown")
        pitch = params.get("pitch_shift", 0)
        f0 = params.get("f0_method", "rmvpe")
        pitch_str = f"+{pitch}" if pitch > 0 else str(pitch)
        return f"**Model**: {model} · **Pitch**: {pitch_str} semitones · **F0**: {f0}"

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))
