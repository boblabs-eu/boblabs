"""Wan 2.2 Video API — text/image → video generation via Wan2.2 (diffusers).

Generates video (MP4) from text prompts and/or images using the Wan 2.2 models.

Supported models:
  • TI2V-5B  — Efficient 5B model, T2V+I2V unified, 720P@24fps (~24GB VRAM)
  • T2V-A14B — MoE 27B (14B active), T2V only, 480P+720P (~32GB+ VRAM)
  • I2V-A14B — MoE 27B (14B active), I2V only, 480P+720P (~32GB+ VRAM)

Endpoints:
  GET  /health   → service status
  GET  /models   → available models
  POST /generate → video generation
"""

import base64
import gc
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

HOST = os.getenv("WAN_HOST", "0.0.0.0")
PORT = int(os.getenv("WAN_PORT", "3019"))
IDLE_UNLOAD_SEC = int(os.getenv("WAN_IDLE_UNLOAD_SEC", "600"))

# Model selection
MODEL_NAME = os.getenv("WAN_MODEL", "TI2V-5B")
# For local-dir mode, point to a pre-downloaded model directory.
# If empty, models are downloaded from HuggingFace on first load.
MODEL_DIR = os.getenv("WAN_MODEL_DIR", "")

# Offloading: move sub-models to CPU when not in use (reduces peak VRAM)
OFFLOAD = os.getenv("WAN_OFFLOAD", "auto")  # "auto", "always", "never"

# Model ID mapping (diffusers)
_MODEL_HF_IDS = {
    "TI2V-5B":  "Wan-AI/Wan2.2-TI2V-5B-Diffusers",
    "T2V-A14B": "Wan-AI/Wan2.2-T2V-A14B-Diffusers",
    "I2V-A14B": "Wan-AI/Wan2.2-I2V-A14B-Diffusers",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("wan-video-api")

# ── Global state ─────────────────────────────────────

_pipe = None
_pipe_model: str | None = None
_model_loaded = False
_model_lock = threading.Lock()
_last_used = 0.0
_active_requests = 0
_active_lock = threading.Lock()
_generate_sem = threading.Semaphore(1)

# Progress tracking for /status endpoint
_generating = False
_current_step = 0
_total_steps = 0
_gen_start_time = 0.0

app = FastAPI(title="Wan-Video API", version="1.0.0")


# ── Model lifecycle ──────────────────────────────────

def _resolve_model_source() -> str:
    """Return the model path or HF repo ID to load from."""
    if MODEL_DIR and os.path.isdir(MODEL_DIR):
        return MODEL_DIR
    hf_id = _MODEL_HF_IDS.get(MODEL_NAME)
    if not hf_id:
        raise ValueError(
            f"Unknown model '{MODEL_NAME}'. "
            f"Valid: {', '.join(_MODEL_HF_IDS.keys())}"
        )
    return hf_id


def _should_offload() -> bool:
    """Decide whether to use CPU offloading based on config."""
    if OFFLOAD == "never":
        return False
    # Always offload — the full pipeline (transformer + VAE decode in float32)
    # exceeds 32 GB VRAM at 1280x704 @ 121 frames.
    return True


def _ensure_model():
    """Load the diffusers pipeline if not already loaded."""
    global _pipe, _model_loaded, _last_used, _pipe_model

    with _model_lock:
        if _model_loaded and _pipe_model == MODEL_NAME:
            _last_used = time.time()
            return

        if _model_loaded:
            _unload_inner()

        logger.info("Loading Wan 2.2 pipeline (model=%s) ...", MODEL_NAME)
        start = time.time()

        source = _resolve_model_source()

        if MODEL_NAME in ("TI2V-5B", "T2V-A14B"):
            from diffusers import WanPipeline, AutoencoderKLWan

            vae = AutoencoderKLWan.from_pretrained(
                source, subfolder="vae", torch_dtype=torch.bfloat16,
            )
            _pipe = WanPipeline.from_pretrained(
                source, vae=vae, torch_dtype=torch.bfloat16,
            )
        elif MODEL_NAME == "I2V-A14B":
            from diffusers import WanImageToVideoPipeline, AutoencoderKLWan
            from transformers import CLIPVisionModel

            image_encoder = CLIPVisionModel.from_pretrained(
                source, subfolder="image_encoder", torch_dtype=torch.bfloat16,
            )
            vae = AutoencoderKLWan.from_pretrained(
                source, subfolder="vae", torch_dtype=torch.bfloat16,
            )
            _pipe = WanImageToVideoPipeline.from_pretrained(
                source, vae=vae, image_encoder=image_encoder,
                torch_dtype=torch.bfloat16,
            )
        else:
            raise ValueError(f"Unknown model: {MODEL_NAME}")

        # Replace default UniPC scheduler — its multistep accumulator has a
        # known device-mismatch bug (CPU vs CUDA tensors at step 2+).
        # Wan 2.2 uses flow matching, so we need FlowMatchEulerDiscreteScheduler.
        from diffusers import FlowMatchEulerDiscreteScheduler
        _pipe.scheduler = FlowMatchEulerDiscreteScheduler.from_config(
            _pipe.scheduler.config
        )

        # Sequential CPU offload — moves individual layers to GPU one at a time
        # rather than whole sub-models. Keeps peak system RAM very low (~2-3 GB)
        # compared to enable_model_cpu_offload() which parks entire sub-models
        # in RAM (~20 GB for T5 + transformer combined, OOM on 30 GB systems).
        # Trade-off: ~50% slower due to per-layer GPU transfers.
        logger.info("Enabling sequential CPU offload (low RAM mode)")
        _pipe.enable_sequential_cpu_offload()

        _pipe_model = MODEL_NAME
        _model_loaded = True
        _last_used = time.time()
        logger.info(
            "Wan 2.2 pipeline loaded in %.1fs (model=%s)",
            time.time() - start, MODEL_NAME,
        )


def _unload_inner():
    """Free the pipeline. Caller must hold _model_lock."""
    global _pipe, _model_loaded, _pipe_model
    if _pipe is not None:
        del _pipe
        _pipe = None
    _model_loaded = False
    _pipe_model = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    logger.info("Wan 2.2 pipeline unloaded.")


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
        description="Text prompt describing the video",
    )
    negative_prompt: str = Field(
        "",
        description="Negative prompt (things to avoid)",
    )
    image: str | None = Field(
        None, description="Base64-encoded image for image-to-video conditioning",
    )
    width: int = Field(1280, ge=128, le=1920, description="Width")
    height: int = Field(704, ge=128, le=1920, description="Height")
    num_frames: int = Field(
        121, ge=9, le=257,
        description="Number of frames (121 = 5s at 24fps)",
    )
    num_inference_steps: int = Field(
        50, ge=1, le=100,
        description="Denoising steps",
    )
    guidance_scale: float = Field(
        5.0, ge=1.0, le=20.0,
        description="CFG guidance scale",
    )
    seed: int = Field(-1, description="Random seed (-1 for random)")
    fps: int = Field(24, ge=1, le=60, description="Output FPS")


class GenerateResponse(BaseModel):
    video: str
    duration_s: float
    width: int
    height: int
    num_frames: int
    fps: int
    model: str
    seed: int


# ── Default negative prompt ──────────────────────────

_DEFAULT_NEGATIVE = (
    "Bright tones, overexposed, static, blurred details, subtitles, "
    "worst quality, low quality, JPEG compression, ugly, incomplete, "
    "extra fingers, poorly drawn hands, poorly drawn faces, deformed, "
    "disfigured, misshapen limbs, fused fingers, messy background"
)


# ── Endpoints ────────────────────────────────────────


@app.get("/health")
def health():
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else ""
    return {
        "status": "ok",
        "service": "wan-video-api",
        "gpu_available": gpu_available,
        "gpu_name": gpu_name,
        "model_loaded": _model_loaded,
        "model": MODEL_NAME,
        "offload": True,
    }


@app.get("/status")
def status():
    """Real-time generation progress. Poll every 5-10s during generation."""
    elapsed = round(time.time() - _gen_start_time, 1) if _generating else 0
    return {
        "generating": _generating,
        "step": _current_step,
        "total_steps": _total_steps,
        "elapsed_s": elapsed,
        "model": MODEL_NAME,
    }


@app.get("/models")
def models():
    return {
        "models": [
            {
                "name": "TI2V-5B",
                "description": "5B unified T2V+I2V, 720P@24fps, runs on 24GB+ GPU",
            },
            {
                "name": "T2V-A14B",
                "description": "MoE 27B (14B active), T2V, 480P+720P, needs 32GB+ GPU",
            },
            {
                "name": "I2V-A14B",
                "description": "MoE 27B (14B active), I2V, 480P+720P, needs 32GB+ GPU",
            },
        ],
        "active": MODEL_NAME,
    }


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    global _active_requests, _last_used, _generating, _current_step, _total_steps, _gen_start_time

    acquired = _generate_sem.acquire(timeout=600)
    if not acquired:
        raise HTTPException(503, "Server busy — another generation is in progress")

    with _active_lock:
        _active_requests += 1
    try:
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        _ensure_model()

        seed = req.seed if req.seed >= 0 else int(time.time()) % (2**31)
        generator = torch.Generator(device="cpu").manual_seed(seed)

        negative = req.negative_prompt or _DEFAULT_NEGATIVE

        logger.info(
            "Generating video: %dx%d, %d frames, seed=%d, model=%s",
            req.width, req.height, req.num_frames, seed, MODEL_NAME,
        )
        t0 = time.time()
        _generating = True
        _current_step = 0
        _total_steps = req.num_inference_steps
        _gen_start_time = t0

        def _progress_callback(pipe, step_index, timestep, callback_kwargs):
            global _current_step
            _current_step = step_index + 1
            return callback_kwargs

        with torch.inference_mode():
            kwargs = dict(
                prompt=req.prompt,
                negative_prompt=negative,
                height=req.height,
                width=req.width,
                num_frames=req.num_frames,
                num_inference_steps=req.num_inference_steps,
                guidance_scale=req.guidance_scale,
                generator=generator,
            )

            # I2V: load and inject image
            if req.image:
                from PIL import Image
                import io

                img_bytes = base64.b64decode(req.image)
                image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                # Resize to match target aspect ratio
                image = image.resize((req.width, req.height), Image.LANCZOS)
                kwargs["image"] = image

            # A14B T2V model supports dual guidance scale
            if MODEL_NAME == "T2V-A14B" and not req.image:
                kwargs["guidance_scale_2"] = 3.0

            kwargs["callback_on_step_end"] = _progress_callback
            output = _pipe(**kwargs)

        _generating = False
        frames = output.frames[0]  # list of PIL Images

        # Encode frames → MP4
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "output.mp4")

            from diffusers.utils import export_to_video
            export_to_video(frames, output_path, fps=req.fps)

            elapsed = time.time() - t0
            logger.info("Video generated in %.1fs", elapsed)

            if not os.path.isfile(output_path):
                raise HTTPException(500, "Pipeline produced no output file")

            video_b64 = base64.b64encode(Path(output_path).read_bytes()).decode()
            duration_s = req.num_frames / req.fps

            return GenerateResponse(
                video=video_b64,
                duration_s=round(duration_s, 2),
                width=req.width,
                height=req.height,
                num_frames=req.num_frames,
                fps=req.fps,
                model=MODEL_NAME,
                seed=seed,
            )

    except HTTPException:
        _generating = False
        raise
    except Exception as e:
        _generating = False
        logger.exception("Generation failed")
        raise HTTPException(500, f"Generation failed: {e}")
    finally:
        with _active_lock:
            _active_requests -= 1
            _last_used = time.time()
        _generate_sem.release()


# ── Main ─────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting Wan-Video API on %s:%d", HOST, PORT)
    logger.info("Model: %s | Offload: %s", MODEL_NAME, OFFLOAD)
    logger.info("Model source: %s", _resolve_model_source())
    uvicorn.run(app, host=HOST, port=PORT, timeout_keep_alive=600)
