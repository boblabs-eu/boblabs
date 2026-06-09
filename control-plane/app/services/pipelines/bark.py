"""Bob Manager — Bark text-to-speech/singing pipeline.

Wraps the bark-api FastAPI service behind the MediaPipeline abstraction.

API contract (gpu-services/bark-api):
    POST /generate  → GenerateResponse (audio: base64 WAV, duration_s, sample_rate)
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
    "speaker": None,
    "temperature": 0.7,
    "silence_padding_ms": 0,
}

_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)


class BarkPipeline(MediaPipeline):
    """Bark text-to-speech / singing pipeline (Suno)."""

    async def generate(self, params: dict) -> PipelineResult:
        clean = self.validate_params(params)

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(f"{self.base_url}/generate", json=clean)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            msg = f"Bark HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            logger.error(msg)
            return PipelineResult(success=False, error=msg, params_used=clean)
        except Exception as exc:
            msg = f"Bark request failed: {exc}"
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

        speaker = params.get("speaker", DEFAULT_PARAMS["speaker"])
        if speaker:
            out["speaker"] = str(speaker)

        out["temperature"] = _clamp(
            float(params.get("temperature", DEFAULT_PARAMS["temperature"])),
            0.1,
            2.0,
        )
        out["silence_padding_ms"] = _clamp(
            int(params.get("silence_padding_ms", DEFAULT_PARAMS["silence_padding_ms"])),
            0,
            2000,
        )

        return out

    def system_prompt(self) -> str:
        return (
            "You are a Bark parameter generator. Translate the user's description "
            "into a JSON payload for Bark text-to-speech.\n\n"
            "Parameters:\n"
            "- prompt (str): text to speak/sing. Use ♪ around lyrics for singing mode.\n"
            "- speaker (str, optional): speaker preset e.g. 'v2/en_speaker_6'\n"
            "- temperature (float): 0.1-2.0 (default 0.7)\n"
            "- silence_padding_ms (int): 0-2000 (default 0)\n\n"
            "Reply with ONLY valid JSON."
        )

    def build_tool_params(self, prompt: str, extra: dict) -> dict:
        params = {"prompt": prompt}
        for key in ("speaker", "temperature", "silence_padding_ms"):
            if key in extra:
                params[key] = extra[key]
        return params

    def tool_description(self) -> str:
        return (
            "bark — text-to-speech and singing (Suno Bark). "
            "Generates speech or singing from text. Use ♪ tokens around lyrics for singing mode. "
            "params: speaker (e.g. v2/en_speaker_6), temperature (0.1-2.0), "
            "silence_padding_ms (0-2000)"
        )

    def format_summary(self, params: dict) -> str:
        prompt = params.get("prompt", "")
        speaker = params.get("speaker", "random")
        temp = params.get("temperature", 0.7)
        return f'**Prompt**: "{prompt[:100]}" · **Speaker**: {speaker} · **Temp**: {temp}'

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))
