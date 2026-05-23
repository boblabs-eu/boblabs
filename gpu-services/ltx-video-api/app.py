"""LTX-Video API — text/image → video generation via LTX-2.3.

Generates video (MP4 with optional audio) from text prompts and/or images.

Supported pipeline modes:
  • distilled  — Fastest inference, 8 predefined sigmas (~30-60s)
  • two_stage  — Production quality, 40 steps with CFG (~2-5 min)
  • two_stage_hq — Highest quality, res_2s sampler

Inputs:
  • prompt  (str, required) — Cinematographic description
  • image   (base64, optional) — Condition on a reference image

Endpoints:
  GET  /health   → service status
  GET  /models   → available pipeline modes
  POST /generate → video generation
"""

import base64
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── Configuration ────────────────────────────────────

HOST = os.getenv("LTX_HOST", "0.0.0.0")
PORT = int(os.getenv("LTX_PORT", "3018"))
IDLE_UNLOAD_SEC = int(os.getenv("LTX_IDLE_UNLOAD_SEC", "600"))

# Model paths (mounted volumes)
CHECKPOINT_PATH = os.getenv(
    "LTX_CHECKPOINT_PATH",
    "/models/ltx-video/ltx-2.3-22b-distilled-1.1.safetensors",
)
UPSAMPLER_PATH = os.getenv(
    "LTX_UPSAMPLER_PATH",
    "/models/ltx-video/ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
)
DISTILLED_LORA_PATH = os.getenv(
    "LTX_DISTILLED_LORA_PATH",
    "/models/ltx-video/ltx-2.3-22b-distilled-lora-384-1.1.safetensors",
)
GEMMA_ROOT = os.getenv("LTX_GEMMA_ROOT", "/models/gemma")
QUANTIZATION = os.getenv("LTX_QUANTIZATION", "fp8-cast")
DEFAULT_PIPELINE = os.getenv("LTX_PIPELINE_MODE", "distilled")
# Layer streaming: stream model layers CPU→GPU one at a time to reduce peak VRAM.
# Requires ~24GB+ free **system RAM** for Gemma 12B.  Set to 0 to disable
# (loads each model directly on GPU in sequence, needs 32GB VRAM).
_streaming_raw = os.getenv("LTX_STREAMING_PREFETCH", "0")
STREAMING_PREFETCH: int | None = int(_streaming_raw) if int(_streaming_raw) > 0 else None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ltx-video-api")

# ── Global state ─────────────────────────────────────

_pipeline = None
_pipeline_mode: str | None = None
_model_loaded = False
_model_lock = threading.Lock()
_last_used = 0.0
_active_requests = 0
_active_lock = threading.Lock()
# Allow only one generation at a time (GPU memory constraint for 22B model)
_generate_sem = threading.Semaphore(1)

app = FastAPI(title="LTX-Video API", version="1.0.0")

# ── Model lifecycle ──────────────────────────────────


def _get_quantization():
    """Return a QuantizationPolicy based on env config, or None."""
    if QUANTIZATION in ("fp8-cast", "fp8-scaled-mm"):
        try:
            from ltx_core.quantization import QuantizationPolicy
            if QUANTIZATION == "fp8-cast":
                return QuantizationPolicy.fp8_cast()
            return QuantizationPolicy.fp8_scaled_mm()
        except Exception as e:
            logger.warning("Failed to load FP8 quantization (%s), running without: %s", QUANTIZATION, e)
    return None


def _ensure_model(mode: str | None = None):
    """Load pipeline if not already loaded (or reload on mode change)."""
    global _pipeline, _model_loaded, _last_used, _pipeline_mode

    mode = mode or DEFAULT_PIPELINE

    with _model_lock:
        if _model_loaded and _pipeline_mode == mode:
            _last_used = time.time()
            return

        # Unload if loaded with different mode
        if _model_loaded:
            _unload_inner()

        logger.info("Loading LTX-2 pipeline (mode=%s) ...", mode)
        start = time.time()
        quant = _get_quantization()

        if mode == "distilled":
            from ltx_pipelines.distilled import DistilledPipeline

            kwargs = dict(
                distilled_checkpoint_path=CHECKPOINT_PATH,
                spatial_upsampler_path=UPSAMPLER_PATH,
                gemma_root=GEMMA_ROOT,
                loras=[],
            )
            if quant:
                kwargs["quantization"] = quant
            _pipeline = DistilledPipeline(**kwargs)

        elif mode in ("two_stage", "two_stage_hq"):
            from ltx_core.loader import (
                LTXV_LORA_COMFY_RENAMING_MAP,
                LoraPathStrengthAndSDOps,
            )

            distilled_lora = []
            if DISTILLED_LORA_PATH and os.path.isfile(DISTILLED_LORA_PATH):
                distilled_lora = [
                    LoraPathStrengthAndSDOps(
                        DISTILLED_LORA_PATH, 0.6, LTXV_LORA_COMFY_RENAMING_MAP,
                    ),
                ]

            if mode == "two_stage":
                from ltx_pipelines.ti2vid_two_stages import TI2VidTwoStagesPipeline
                PipelineCls = TI2VidTwoStagesPipeline
            else:
                from ltx_pipelines.ti2vid_two_stages_hq import TI2VidTwoStagesHQPipeline
                PipelineCls = TI2VidTwoStagesHQPipeline

            kwargs = dict(
                checkpoint_path=CHECKPOINT_PATH,
                distilled_lora=distilled_lora,
                spatial_upsampler_path=UPSAMPLER_PATH,
                gemma_root=GEMMA_ROOT,
                loras=[],
            )
            if quant:
                kwargs["quantization"] = quant
            _pipeline = PipelineCls(**kwargs)
        else:
            raise ValueError(f"Unknown pipeline mode: {mode}")

        _pipeline_mode = mode
        _model_loaded = True
        _last_used = time.time()
        logger.info(
            "LTX-2 pipeline loaded in %.1fs (mode=%s)",
            time.time() - start, mode,
        )


def _unload_inner():
    """Free the pipeline and clear VRAM. Caller must hold _model_lock."""
    global _pipeline, _model_loaded, _pipeline_mode
    if _pipeline is not None:
        del _pipeline
        _pipeline = None
    _model_loaded = False
    _pipeline_mode = None
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    logger.info("LTX-2 pipeline unloaded.")


def _idle_watcher():
    """Background thread: unload model after idle timeout."""
    while True:
        time.sleep(30)
        if not _model_loaded:
            continue
        with _active_lock:
            if _active_requests > 0:
                continue
        if time.time() - _last_used > IDLE_UNLOAD_SEC:
            with _model_lock:
                if _model_loaded and _active_requests == 0:
                    logger.info("Idle timeout — unloading model.")
                    _unload_inner()


threading.Thread(target=_idle_watcher, daemon=True).start()

# ── Request / Response schemas ───────────────────────


class GenerateRequest(BaseModel):
    prompt: str = Field(
        ..., min_length=1, max_length=2000,
        description="Cinematographic text prompt describing the video",
    )
    image: str | None = Field(
        None, description="Base64-encoded image for image-to-video conditioning",
    )
    width: int = Field(768, ge=128, le=1920, description="Width (divisible by 32)")
    height: int = Field(512, ge=128, le=1920, description="Height (divisible by 32)")
    num_frames: int = Field(
        97, ge=9, le=257,
        description="Frame count (must be 8k+1, e.g. 9, 17, 25, ..., 97, ..., 257)",
    )
    num_inference_steps: int = Field(
        40, ge=1, le=100,
        description="Denoising steps (ignored for distilled mode)",
    )
    guidance_scale: float = Field(
        3.0, ge=1.0, le=20.0,
        description="CFG scale (ignored for distilled mode)",
    )
    seed: int = Field(-1, description="Random seed (-1 for random)")
    frame_rate: float = Field(25.0, ge=1.0, le=60.0, description="Output FPS")
    enhance_prompt: bool = Field(
        False, description="Auto-enhance prompt via LLM",
    )


class GenerateResponse(BaseModel):
    video: str
    duration_s: float
    width: int
    height: int
    num_frames: int
    fps: float
    pipeline_mode: str
    seed: int


# ── Endpoints ────────────────────────────────────────


@app.get("/health")
def health():
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else ""
    return {
        "status": "ok",
        "service": "ltx-video-api",
        "gpu_available": gpu_available,
        "gpu_name": gpu_name,
        "model_loaded": _model_loaded,
        "pipeline_mode": _pipeline_mode or DEFAULT_PIPELINE,
        "quantization": QUANTIZATION,
    }


@app.get("/models")
def models():
    return {
        "models": [
            {"name": "distilled", "description": "Fastest inference (8 steps, ~30-60s)"},
            {"name": "two_stage", "description": "Production quality (40 steps, ~2-5 min)"},
            {"name": "two_stage_hq", "description": "Highest quality (res_2s sampler)"},
        ],
        "active": _pipeline_mode or DEFAULT_PIPELINE,
        "checkpoint": os.path.basename(CHECKPOINT_PATH),
    }


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    global _active_requests, _last_used

    from ltx_core.model.video_vae import TilingConfig, get_video_chunks_number
    from ltx_pipelines.utils.media_io import encode_video

    # ── Validate dimensions ──
    if req.width % 32 != 0:
        raise HTTPException(400, f"width must be divisible by 32, got {req.width}")
    if req.height % 32 != 0:
        raise HTTPException(400, f"height must be divisible by 32, got {req.height}")
    if (req.num_frames - 1) % 8 != 0:
        raise HTTPException(
            400,
            f"num_frames must be 8k+1 (e.g. 9,17,25,...,97,...,257), got {req.num_frames}",
        )

    # Acquire generation semaphore (single concurrent generation)
    acquired = _generate_sem.acquire(timeout=600)
    if not acquired:
        raise HTTPException(503, "Server busy — another generation is in progress")

    with _active_lock:
        _active_requests += 1
    try:
        # Free any lingering GPU memory before loading models
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        _ensure_model()

        seed = req.seed if req.seed >= 0 else int(time.time()) % (2**31)

        # CRITICAL: inference_mode disables gradient tracking, freeing several
        # GB of VRAM that would otherwise hold activation tensors for backprop.
        # The LTX-2 CLI applies this decorator on its main(); we must do the same.
        with torch.inference_mode(), tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "output.mp4")

            # Image conditioning
            images_list = []
            if req.image:
                from ltx_pipelines.utils.args import ImageConditioningInput

                img_bytes = base64.b64decode(req.image)
                img_path = os.path.join(tmpdir, "input_image.png")
                Path(img_path).write_bytes(img_bytes)
                images_list = [ImageConditioningInput(img_path, 0, 1.0, 33)]

            tiling_config = TilingConfig.default()
            video_chunks_number = get_video_chunks_number(req.num_frames, tiling_config)

            logger.info(
                "Generating video: %dx%d, %d frames, seed=%d, mode=%s",
                req.width, req.height, req.num_frames, seed, _pipeline_mode,
            )
            t0 = time.time()

            if _pipeline_mode == "distilled":
                # DistilledPipeline.__call__ returns (video_iterator, audio)
                video, audio = _pipeline(
                    prompt=req.prompt,
                    seed=seed,
                    height=req.height,
                    width=req.width,
                    num_frames=req.num_frames,
                    frame_rate=req.frame_rate,
                    images=images_list,
                    tiling_config=tiling_config,
                    enhance_prompt=req.enhance_prompt,
                    streaming_prefetch_count=STREAMING_PREFETCH,
                )
            else:
                # TI2VidTwoStagesPipeline needs guidance params + negative_prompt
                from ltx_core.components.guiders import MultiModalGuiderParams

                video_guider = MultiModalGuiderParams(
                    cfg_scale=req.guidance_scale,
                    stg_scale=1.0,
                    rescale_scale=0.7,
                    modality_scale=3.0,
                    skip_step=0,
                    stg_blocks=[29],
                )
                audio_guider = MultiModalGuiderParams(
                    cfg_scale=7.0,
                    stg_scale=1.0,
                    rescale_scale=0.7,
                    modality_scale=3.0,
                    skip_step=0,
                    stg_blocks=[29],
                )

                video, audio = _pipeline(
                    prompt=req.prompt,
                    negative_prompt="",
                    seed=seed,
                    height=req.height,
                    width=req.width,
                    num_frames=req.num_frames,
                    frame_rate=req.frame_rate,
                    num_inference_steps=req.num_inference_steps,
                    video_guider_params=video_guider,
                    audio_guider_params=audio_guider,
                    images=images_list,
                    tiling_config=tiling_config,
                    enhance_prompt=req.enhance_prompt,
                    streaming_prefetch_count=STREAMING_PREFETCH,
                )

            # Encode tensors → MP4 file
            encode_video(
                video=video,
                fps=req.frame_rate,
                audio=audio,
                output_path=output_path,
                video_chunks_number=video_chunks_number,
            )

            elapsed = time.time() - t0
            logger.info("Video generated in %.1fs", elapsed)

            if not os.path.isfile(output_path):
                raise HTTPException(500, "Pipeline produced no output file")

            video_b64 = base64.b64encode(Path(output_path).read_bytes()).decode()
            duration_s = req.num_frames / req.frame_rate

            return GenerateResponse(
                video=video_b64,
                duration_s=round(duration_s, 2),
                width=req.width,
                height=req.height,
                num_frames=req.num_frames,
                fps=req.frame_rate,
                pipeline_mode=_pipeline_mode,
                seed=seed,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Generation failed")
        raise HTTPException(500, f"Generation failed: {e}")
    finally:
        with _active_lock:
            _active_requests -= 1
            _last_used = time.time()
        _generate_sem.release()


# ── Main ─────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting LTX-Video API on %s:%d", HOST, PORT)
    logger.info("Pipeline: %s | Quantization: %s | Streaming prefetch: %s",
                DEFAULT_PIPELINE, QUANTIZATION, STREAMING_PREFETCH or "disabled")
    logger.info("Checkpoint: %s", CHECKPOINT_PATH)
    logger.info("Gemma root: %s", GEMMA_ROOT)
    uvicorn.run(app, host=HOST, port=PORT, timeout_keep_alive=600)
