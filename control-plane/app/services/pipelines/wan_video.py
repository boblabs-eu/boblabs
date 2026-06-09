"""Bob Manager — Wan 2.2 Video generation pipeline.

Wraps the wan-video-api FastAPI service behind the MediaPipeline abstraction.

API contract (gpu-services/wan-video-api):
    POST /generate  → GenerateResponse (video: base64 MP4, duration_s, width, height, ...)
    GET  /health    → {status, gpu_available, model_loaded, model, offload, ...}
    GET  /models    → {models: [...], active}
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.pipelines.base import MediaPipeline, PipelineResult

logger = logging.getLogger(__name__)

DEFAULT_PARAMS: dict[str, Any] = {
    "width": 1280,
    "height": 704,
    "num_frames": 121,
    "num_inference_steps": 50,
    "guidance_scale": 5.0,
    "seed": -1,
    "fps": 24,
}

# Video generation can be extremely slow with sequential CPU offload on
# large-RAM servers (e.g. 2h+ at float32).  4-hour read timeout.
_TIMEOUT = httpx.Timeout(connect=10.0, read=14400.0, write=10.0, pool=10.0)


class WanVideoPipeline(MediaPipeline):
    """Wan 2.2 text/image → video pipeline (Wan-AI, diffusers)."""

    async def generate(self, params: dict) -> PipelineResult:
        clean = self.validate_params(params)

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(f"{self.base_url}/generate", json=clean)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            msg = f"Wan-Video HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            logger.error(msg)
            return PipelineResult(success=False, error=msg, params_used=clean)
        except Exception as exc:
            msg = f"Wan-Video request failed: {exc}"
            logger.error(msg)
            return PipelineResult(success=False, error=msg, params_used=clean)

        return PipelineResult(
            success=True,
            media_type="video",
            media_url=data.get("video", ""),
            duration_s=data.get("duration_s", 0.0),
            params_used=clean,
            raw=data,
        )

    def validate_params(self, params: dict) -> dict:
        out: dict = {}

        out["prompt"] = str(params.get("prompt", "")).strip()
        if not out["prompt"]:
            raise ValueError("Missing or empty 'prompt'")

        # Negative prompt (optional)
        neg = str(params.get("negative_prompt", "")).strip()
        if neg:
            out["negative_prompt"] = neg

        # Image (optional, base64 string for I2V)
        if params.get("image"):
            out["image"] = params["image"]

        w = int(params.get("width", DEFAULT_PARAMS["width"]))
        h = int(params.get("height", DEFAULT_PARAMS["height"]))
        # Clamp to multiples of 16
        out["width"] = max(128, min(1920, (w // 16) * 16))
        out["height"] = max(128, min(1920, (h // 16) * 16))

        out["num_frames"] = _clamp(
            int(params.get("num_frames", DEFAULT_PARAMS["num_frames"])),
            9,
            257,
        )
        out["num_inference_steps"] = _clamp(
            int(params.get("num_inference_steps", DEFAULT_PARAMS["num_inference_steps"])),
            1,
            100,
        )
        out["guidance_scale"] = _clamp(
            float(params.get("guidance_scale", DEFAULT_PARAMS["guidance_scale"])),
            1.0,
            20.0,
        )
        out["seed"] = int(params.get("seed", DEFAULT_PARAMS["seed"]))
        out["fps"] = _clamp(
            int(params.get("fps", DEFAULT_PARAMS["fps"])),
            1,
            60,
        )

        return out

    def system_prompt(self) -> str:
        return (
            "You are a video generation parameter generator for Wan 2.2. "
            "Translate the user's description into a JSON payload.\n\n"
            "Parameters:\n"
            "- prompt (str): Detailed description of the video. "
            "  Describe the scene, action, mood, lighting, camera movement. "
            "  Keep under 200 words.\n"
            "- negative_prompt (str): Things to avoid (optional)\n"
            "- image (str): Base64-encoded image for image-to-video (optional)\n"
            "- width (int): 128-1920, divisible by 16 (default 1280)\n"
            "- height (int): 128-1920, divisible by 16 (default 704)\n"
            "- num_frames (int): 9-257, default 121 (5s at 24fps)\n"
            "- num_inference_steps (int): 1-100, default 50\n"
            "- guidance_scale (float): 1-20, default 5.0\n"
            "- seed (int): -1 for random\n"
            "- fps (int): 1-60, default 24\n\n"
            "Reply with ONLY valid JSON."
        )

    def build_tool_params(self, prompt: str, extra: dict) -> dict:
        params: dict = {"prompt": prompt}
        for key in (
            "width",
            "height",
            "num_frames",
            "num_inference_steps",
            "guidance_scale",
            "seed",
            "fps",
            "negative_prompt",
        ):
            if key in extra:
                params[key] = extra[key]
        if "input_audio_b64" in extra:
            params["image"] = extra["input_audio_b64"]
        if extra.get("image"):
            params["image"] = extra["image"]
        return params

    def tool_description(self) -> str:
        return (
            "wan_video — text/image → video via Wan 2.2 (5B unified model). "
            "Generates 720P video at 24fps from text prompts. "
            "Optional image conditioning for image-to-video. "
            "params: width (128-1920), height (128-1920), num_frames (9-257, default 121), "
            "num_inference_steps (1-100), guidance_scale (1-20), seed, fps (1-60)"
        )

    def format_summary(self, params: dict) -> str:
        prompt = params.get("prompt", "")
        w = params.get("width", 1280)
        h = params.get("height", 704)
        nf = params.get("num_frames", 121)
        fps = params.get("fps", 24)
        dur = nf / fps if fps else 0
        has_img = "image" in params
        suffix = " (+image conditioning)" if has_img else ""
        return (
            f'**Prompt**: "{prompt[:100]}" · '
            f"**Resolution**: {w}×{h} · "
            f"**Duration**: {dur:.1f}s ({nf} frames @ {fps}fps)"
            f"{suffix}"
        )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False


def _clamp(val, lo, hi):
    return max(lo, min(hi, val))
