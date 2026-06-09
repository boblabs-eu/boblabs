"""Bob Manager — LTX-Video generation pipeline.

Wraps the ltx-video-api FastAPI service behind the MediaPipeline abstraction.

API contract (gpu-services/ltx-video-api):
    POST /generate  → GenerateResponse (video: base64 MP4, duration_s, width, height, ...)
    GET  /health    → {status, gpu_available, model_loaded, pipeline_mode, ...}
    GET  /models    → {models: [...], active, checkpoint}
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.pipelines.base import MediaPipeline, PipelineResult

logger = logging.getLogger(__name__)

DEFAULT_PARAMS: dict[str, Any] = {
    "width": 768,
    "height": 512,
    "num_frames": 97,
    "num_inference_steps": 40,
    "guidance_scale": 3.0,
    "seed": -1,
    "frame_rate": 25.0,
}

# Video generation with layer streaming on 32GB GPUs can be very slow on first
# run (~10-20 min cold start). Use a generous read timeout.
_TIMEOUT = httpx.Timeout(connect=10.0, read=14400.0, write=10.0, pool=10.0)


class LTXVideoPipeline(MediaPipeline):
    """LTX-2.3 text/image → video pipeline (Lightricks)."""

    async def generate(self, params: dict) -> PipelineResult:
        clean = self.validate_params(params)

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(f"{self.base_url}/generate", json=clean)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            msg = f"LTX-Video HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            logger.error(msg)
            return PipelineResult(success=False, error=msg, params_used=clean)
        except Exception as exc:
            msg = f"LTX-Video request failed: {exc}"
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

        # Image (optional, base64 string)
        if params.get("image"):
            out["image"] = params["image"]

        w = int(params.get("width", DEFAULT_PARAMS["width"]))
        h = int(params.get("height", DEFAULT_PARAMS["height"]))
        # Clamp to multiples of 32
        out["width"] = max(128, min(1920, (w // 32) * 32))
        out["height"] = max(128, min(1920, (h // 32) * 32))

        nf = int(params.get("num_frames", DEFAULT_PARAMS["num_frames"]))
        # Snap to nearest 8k+1 value
        k = max(1, round((nf - 1) / 8))
        out["num_frames"] = min(257, max(9, k * 8 + 1))

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
        out["frame_rate"] = _clamp(
            float(params.get("frame_rate", DEFAULT_PARAMS["frame_rate"])),
            1.0,
            60.0,
        )

        if params.get("enhance_prompt"):
            out["enhance_prompt"] = True

        return out

    def system_prompt(self) -> str:
        return (
            "You are a video generation parameter generator for LTX-2.3. "
            "Translate the user's description into a JSON payload.\n\n"
            "Parameters:\n"
            "- prompt (str): Detailed cinematographic description of the video. "
            "  Start with the main action, add specific details about movements, "
            "  character appearances, background, camera angles, lighting. "
            "  Keep under 200 words.\n"
            "- width (int): 128-1920, divisible by 32 (default 768)\n"
            "- height (int): 128-1920, divisible by 32 (default 512)\n"
            "- num_frames (int): Must be 8k+1 (e.g. 97 ≈ 4s, 121 ≈ 5s at 25fps)\n"
            "- num_inference_steps (int): 1-100, default 40\n"
            "- guidance_scale (float): 1-20, default 3.0\n"
            "- seed (int): -1 for random\n"
            "- frame_rate (float): 1-60, default 25\n\n"
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
            "frame_rate",
            "enhance_prompt",
        ):
            if key in extra:
                params[key] = extra[key]
        # If an input file was provided (image), inject as base64
        if "input_audio_b64" in extra:
            # For video pipelines, input_file is likely an image
            params["image"] = extra["input_audio_b64"]
        if extra.get("image"):
            params["image"] = extra["image"]
        return params

    def tool_description(self) -> str:
        return (
            "ltx_video — text/image → video via LTX-2.3 (22B DiT model). "
            "Generates synchronized audio+video from text prompts. "
            "Optional image conditioning for image-to-video. "
            "params: width (128-1920), height (128-1920), num_frames (8k+1, e.g. 97), "
            "num_inference_steps (1-100), guidance_scale (1-20), seed, frame_rate (1-60)"
        )

    def format_summary(self, params: dict) -> str:
        prompt = params.get("prompt", "")
        w = params.get("width", 768)
        h = params.get("height", 512)
        nf = params.get("num_frames", 97)
        fps = params.get("frame_rate", 25.0)
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


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))
