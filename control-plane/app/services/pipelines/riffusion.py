"""Bob Manager — Riffusion audio generation pipeline.

Wraps the riffusion-hobby Flask API (POST /run_inference/) behind
the MediaPipeline abstraction.

API contract:
    Input:  InferenceInput  (start, end, alpha, num_inference_steps, seed_image_id)
    Output: InferenceOutput (image: data:image/jpeg;base64,…,
                             audio: data:audio/mpeg;base64,…,
                             duration_s: float)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.pipelines.base import MediaPipeline, PipelineResult

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────

VALID_SEED_IMAGES = frozenset({"og_beat", "vibes", "agile", "marim", "motorway"})

DEFAULT_PARAMS: dict[str, Any] = {
    "alpha": 0.0,
    "num_inference_steps": 50,
    "seed_image_id": "og_beat",
}

DEFAULT_PROMPT_PARAMS: dict[str, Any] = {
    "seed": 42,
    "denoising": 0.75,
    "guidance": 7.0,
}

_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)

# ── System prompt for LLM param generation ───────────

_SYSTEM_PROMPT = """\
You are a Riffusion parameter generator.  Translate the user's natural-language
description into a valid JSON payload for the Riffusion inference API.

### How Riffusion works
Riffusion interpolates between two text prompts:
  • **start** – the beginning sound / style.
  • **end**   – the ending sound / style.
  • **alpha** – blend ratio (0.0 = 100 % start, 1.0 = 100 % end, 0.5 = equal mix).

For a *single* style (no transition) use the **same** prompt for start and end,
with alpha = 0.0.

### Seed images (initial rhythm/feel — MUST be one of these exact IDs)
  • "og_beat"  — generic beat, good all-round default
  • "vibes"    — ambient / chill textures
  • "agile"    — fast / energetic rhythms
  • "marim"    — marimba / percussive tones
  • "motorway" — driving / steady beat

### Per-prompt parameters
| field       | type  | range      | default | notes                              |
|-------------|-------|------------|---------|------------------------------------|
| prompt      | str   | —          | —       | descriptive text                   |
| seed        | int   | 0 – 2³¹   | 42      | change for variation               |
| denoising   | float | 0.0 – 1.0 | 0.75    | higher = more creative             |
| guidance    | float | 1.0 – 20  | 7.0     | higher = follows prompt more       |

### Top-level parameters
| field                | type  | range   | default   |
|----------------------|-------|---------|-----------|
| alpha                | float | 0 – 1  | 0.0       |
| num_inference_steps  | int   | 20 – 80| 50        |
| seed_image_id        | str   | see above | "og_beat"|

### Response format
Reply with **ONLY** valid JSON — no markdown fences, no explanation.

Example:
{"start":{"prompt":"jazz piano smooth","seed":42,"denoising":0.75,"guidance":7.0},\
"end":{"prompt":"jazz piano smooth","seed":42,"denoising":0.75,"guidance":7.0},\
"alpha":0.0,"num_inference_steps":50,"seed_image_id":"og_beat"}\
"""


class RiffusionPipeline(MediaPipeline):
    """Riffusion audio generation pipeline."""

    # ── Core interface ───────────────────────────────

    async def generate(self, params: dict) -> PipelineResult:
        """Call POST /run_inference/ with validated params."""
        clean = self.validate_params(params)

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{self.base_url}/run_inference/",
                    json=clean,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            msg = f"Riffusion HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.error(msg)
            return PipelineResult(success=False, error=msg, params_used=clean)
        except Exception as exc:
            msg = f"Riffusion request failed: {exc}"
            logger.error(msg)
            return PipelineResult(success=False, error=msg, params_used=clean)

        return PipelineResult(
            success=True,
            media_type="audio",
            media_url=data.get("audio", ""),
            preview_url=data.get("image", ""),
            duration_s=data.get("duration_s", 0.0),
            params_used=clean,
            raw=data,
        )

    def validate_params(self, params: dict) -> dict:
        """Clamp, fill defaults, reject bad values."""
        out: dict = {}

        # Top-level
        out["alpha"] = _clamp(float(params.get("alpha", DEFAULT_PARAMS["alpha"])), 0.0, 1.0)
        out["num_inference_steps"] = _clamp(
            int(params.get("num_inference_steps", DEFAULT_PARAMS["num_inference_steps"])),
            20,
            80,
        )
        sid = params.get("seed_image_id", DEFAULT_PARAMS["seed_image_id"])
        out["seed_image_id"] = sid if sid in VALID_SEED_IMAGES else "og_beat"

        # Start / end prompts
        for key in ("start", "end"):
            raw = params.get(key, {})
            if isinstance(raw, str):
                raw = {"prompt": raw}
            prompt_text = str(raw.get("prompt", "")).strip()
            if not prompt_text:
                raise ValueError(f"Missing or empty '{key}.prompt'")
            out[key] = {
                "prompt": prompt_text,
                "seed": int(raw.get("seed", DEFAULT_PROMPT_PARAMS["seed"])),
                "denoising": _clamp(
                    float(raw.get("denoising", DEFAULT_PROMPT_PARAMS["denoising"])),
                    0.0,
                    1.0,
                ),
                "guidance": _clamp(
                    float(raw.get("guidance", DEFAULT_PROMPT_PARAMS["guidance"])),
                    1.0,
                    20.0,
                ),
            }

        return out

    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    async def health_check(self) -> bool:
        """Probe GET /run_inference/ — expect 405 (Method Not Allowed)."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self.base_url}/run_inference/")
                return resp.status_code in (200, 405, 422)
        except Exception:
            return False

    # ── Helpers ──────────────────────────────────────

    def build_tool_params(self, prompt: str, extra: dict) -> dict:
        """Build riffusion params from prompt + extra_args."""
        start_prompt = extra.get("start_prompt", prompt)
        end_prompt = extra.get("end_prompt", start_prompt)
        return {
            "start": {
                "prompt": start_prompt,
                "seed": int(extra.get("seed", DEFAULT_PROMPT_PARAMS["seed"])),
                "denoising": float(extra.get("denoising", DEFAULT_PROMPT_PARAMS["denoising"])),
                "guidance": float(extra.get("guidance", DEFAULT_PROMPT_PARAMS["guidance"])),
            },
            "end": {
                "prompt": end_prompt,
                "seed": int(extra.get("seed", DEFAULT_PROMPT_PARAMS["seed"])),
                "denoising": float(extra.get("denoising", DEFAULT_PROMPT_PARAMS["denoising"])),
                "guidance": float(extra.get("guidance", DEFAULT_PROMPT_PARAMS["guidance"])),
            },
            "alpha": float(extra.get("alpha", DEFAULT_PARAMS["alpha"])),
            "num_inference_steps": int(
                extra.get("num_inference_steps", DEFAULT_PARAMS["num_inference_steps"])
            ),
            "seed_image_id": extra.get("seed_image_id", DEFAULT_PARAMS["seed_image_id"]),
        }

    def tool_description(self) -> str:
        return (
            "riffusion — text-to-audio via spectrogram diffusion. "
            "Interpolates between start and end prompts (use same for both if no transition). "
            "extra_args: start_prompt, end_prompt, alpha (0-1 blend), "
            "seed_image_id (og_beat|vibes|agile|marim|motorway), "
            "num_inference_steps (20-80), seed, denoising (0-1), guidance (1-20)"
        )

    def format_summary(self, params: dict) -> str:
        """Human-readable summary of generation parameters."""
        s = params.get("start", {})
        e = params.get("end", {})
        same = s.get("prompt") == e.get("prompt")
        lines = []
        if same:
            lines.append(f'**Prompt**: "{s.get("prompt")}"')
        else:
            lines.append(f'**Start**: "{s.get("prompt")}" → **End**: "{e.get("prompt")}"')
        lines.append(
            f"**Alpha**: {params.get('alpha')} · "
            f"**Seed image**: {params.get('seed_image_id')} · "
            f"**Steps**: {params.get('num_inference_steps')} · "
            f"**Seeds**: {s.get('seed')}/{e.get('seed')}"
        )
        return "\n".join(lines)


# ── Utility ──────────────────────────────────────────


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))
