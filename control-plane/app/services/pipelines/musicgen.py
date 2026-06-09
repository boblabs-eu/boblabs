"""Bob Manager — MusicGen audio generation pipeline.

Wraps the musicgen-api FastAPI service behind the MediaPipeline abstraction.

API contract (gpu-services/musicgen-api):
    POST /generate  → GenerateResponse (audio: base64 WAV, duration_s, sample_rate, model)
    GET  /health    → {status, gpu_available, model_loaded, ...}
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.pipelines.base import MediaPipeline, PipelineResult

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────

DEFAULT_PARAMS: dict[str, Any] = {
    "duration": 15.0,
    "model": "medium",
    "temperature": 1.0,
    "top_k": 250,
    "top_p": 0.0,
}

_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)


class MusicGenPipeline(MediaPipeline):
    """MusicGen text-to-music pipeline (Meta AudioCraft)."""

    async def generate(self, params: dict) -> PipelineResult:
        clean = self.validate_params(params)

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(f"{self.base_url}/generate", json=clean)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            msg = f"MusicGen HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            logger.error(msg)
            return PipelineResult(success=False, error=msg, params_used=clean)
        except Exception as exc:
            msg = f"MusicGen request failed: {exc}"
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
        out["prompt"] = str(params.get("prompt", "")).strip()
        if not out["prompt"]:
            raise ValueError("Missing or empty 'prompt'")

        out["duration"] = _clamp(
            float(params.get("duration", DEFAULT_PARAMS["duration"])), 1.0, 30.0
        )

        model = str(params.get("model", DEFAULT_PARAMS["model"]))
        if model not in ("small", "medium", "large", "melody"):
            model = "medium"
        out["model"] = model

        out["temperature"] = _clamp(
            float(params.get("temperature", DEFAULT_PARAMS["temperature"])), 0.1, 2.0
        )
        out["top_k"] = _clamp(int(params.get("top_k", DEFAULT_PARAMS["top_k"])), 0, 1000)
        out["top_p"] = _clamp(float(params.get("top_p", DEFAULT_PARAMS["top_p"])), 0.0, 1.0)

        # Optional audio inputs (base64)
        if params.get("continuation_audio"):
            out["continuation_audio"] = params["continuation_audio"]
        if params.get("melody_audio") and model == "melody":
            out["melody_audio"] = params["melody_audio"]

        return out

    def system_prompt(self) -> str:
        return (
            "You are a MusicGen parameter generator. Translate the user's description "
            "into a JSON payload for MusicGen.\n\n"
            "Parameters:\n"
            "- prompt (str): descriptive text of the music\n"
            "- duration (float): 1-30 seconds\n"
            "- model: small|medium|large|melody\n"
            "- temperature (float): 0.1-2.0 (default 1.0)\n"
            "- top_k (int): 0-1000 (default 250)\n"
            "- top_p (float): 0-1 (default 0)\n\n"
            "Reply with ONLY valid JSON."
        )

    def build_tool_params(self, prompt: str, extra: dict) -> dict:
        params = {"prompt": prompt}
        for key in (
            "duration",
            "model",
            "temperature",
            "top_k",
            "top_p",
            "continuation_audio",
            "melody_audio",
        ):
            if key in extra:
                params[key] = extra[key]
        # If an input_audio_b64 was injected by the handler (from input_file),
        # treat it as continuation_audio by default
        if "input_audio_b64" in extra and "continuation_audio" not in params:
            params["continuation_audio"] = extra["input_audio_b64"]
        return params

    def tool_description(self) -> str:
        return (
            "musicgen — text-to-music generation (Meta AudioCraft). "
            "Generates instrumental music from text prompts. "
            "params: duration (1-30s), model (small/medium/large/melody), "
            "temperature, top_k, top_p, continuation_audio (base64), "
            "melody_audio (base64, melody model only)"
        )

    def format_summary(self, params: dict) -> str:
        prompt = params.get("prompt", "")
        model = params.get("model", "medium")
        dur = params.get("duration", 15)
        has_cont = "continuation_audio" in params
        has_mel = "melody_audio" in params
        suffix = ""
        if has_cont:
            suffix += " (+continuation)"
        if has_mel:
            suffix += " (+melody conditioning)"
        return f'**Prompt**: "{prompt[:100]}" · **Model**: {model} · **Duration**: {dur}s{suffix}'

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))
