"""Bob Manager — CoquiTTS (XTTS v2) text-to-speech pipeline.

Wraps the coqui-tts-api FastAPI service behind the MediaPipeline abstraction.

API contract (gpu-services/coqui-tts-api):
    POST /generate  → GenerateResponse (audio: base64 WAV, duration_s, sample_rate)
    GET  /health    → {status, gpu_available, model_loaded, speakers_available, ...}
    GET  /speakers  → {speakers: [str]}
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.pipelines.base import MediaPipeline, PipelineResult

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────

DEFAULT_PARAMS: dict[str, Any] = {
    "language": "en",
    "speed": 1.0,
    "temperature": 0.65,
}

_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)


class CoquiTTSPipeline(MediaPipeline):
    """CoquiTTS / XTTS v2 text-to-speech pipeline with voice cloning."""

    async def generate(self, params: dict) -> PipelineResult:
        clean = self.validate_params(params)

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(f"{self.base_url}/generate", json=clean)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            msg = f"CoquiTTS HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            logger.error(msg)
            return PipelineResult(success=False, error=msg, params_used=clean)
        except Exception as exc:
            msg = f"CoquiTTS request failed: {exc}"
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

        out["language"] = str(params.get("language", DEFAULT_PARAMS["language"]))

        # Speaker: either speaker_name (pre-saved) or speaker_wav (base64)
        speaker_name = params.get("speaker_name")
        speaker_wav = params.get("speaker_wav")
        if speaker_name:
            out["speaker_name"] = str(speaker_name)
        elif speaker_wav:
            out["speaker_wav"] = str(speaker_wav)
        # If neither provided, the API will return 400 — that's fine

        out["speed"] = _clamp(
            float(params.get("speed", DEFAULT_PARAMS["speed"])),
            0.5, 2.0,
        )
        out["temperature"] = _clamp(
            float(params.get("temperature", DEFAULT_PARAMS["temperature"])),
            0.1, 1.0,
        )

        return out

    def system_prompt(self) -> str:
        return (
            "You are a CoquiTTS (XTTS v2) parameter generator. Translate the user's "
            "description into a JSON payload for text-to-speech generation.\n\n"
            "Parameters:\n"
            "- prompt (str): text to speak\n"
            "- language (str): language code — en, es, fr, de, it, pt, pl, tr, ru, nl, "
            "cs, ar, zh-cn, ja, ko, hu, hi (default: en)\n"
            "- speaker_name (str, optional): name of a pre-saved speaker voice\n"
            "- speaker_wav (str, optional): base64 WAV of reference speaker (~6s)\n"
            "- speed (float): 0.5-2.0 (default 1.0)\n"
            "- temperature (float): 0.1-1.0 (default 0.65)\n\n"
            "Either speaker_name or speaker_wav is required.\n"
            "Reply with ONLY valid JSON."
        )

    def build_tool_params(self, prompt: str, extra: dict) -> dict:
        params: dict[str, Any] = {"prompt": prompt}
        for key in ("language", "speaker_name", "speaker_wav", "speed", "temperature"):
            if key in extra:
                params[key] = extra[key]
        # If input_audio_b64 is provided (from file input), use as speaker reference
        if "input_audio_b64" in extra and "speaker_wav" not in params:
            params["speaker_wav"] = extra["input_audio_b64"]
        return params

    def tool_description(self) -> str:
        return (
            "coqui_tts — high-quality text-to-speech with voice cloning (XTTS v2). "
            "Generates natural speech from text. Supports 17 languages and voice cloning "
            "from a ~6s reference audio. "
            "params: language (en/es/fr/de/...), speaker_name (pre-saved voice), "
            "speaker_wav (base64 reference audio), speed (0.5-2.0), temperature (0.1-1.0)"
        )

    def format_summary(self, params: dict) -> str:
        prompt = params.get("prompt", "")
        lang = params.get("language", "en")
        speaker = params.get("speaker_name", "custom" if params.get("speaker_wav") else "none")
        speed = params.get("speed", 1.0)
        return f'**Prompt**: "{prompt[:100]}" · **Lang**: {lang} · **Speaker**: {speaker} · **Speed**: {speed}'

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))
