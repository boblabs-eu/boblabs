# Installing Wan 2.2 Video Generation — One-Shot Guide

Wan 2.2 generates 720P video at 24fps from text prompts (and optional image conditioning).
This guide uses the **TI2V-5B** model — a 5B-parameter unified text+image → video model
that runs comfortably on a 24GB+ GPU (RTX 4090 / RTX 5090).

> **Compared to LTX-Video**: Wan 2.2 is much simpler to install — Apache 2.0 license
> (no gated models), uses HuggingFace diffusers (no custom monorepo), and the 5B model
> needs far less VRAM and RAM than LTX-2.3's 22B model.

---

## Prerequisites

| Requirement | Minimum |
|---|---|
| NVIDIA GPU | 24 GB VRAM (RTX 4090 / 5090) |
| System RAM | 16 GB (32 GB recommended) |
| Disk Space | ~30 GB for model weights (auto-downloaded) |
| Docker | Docker Engine + `nvidia-container-toolkit` |
| OS | Linux (tested on Ubuntu 22.04 / 24.04) |

> **No swap needed.** The 5B model is small enough that mmap won't exhaust system memory.

---

## Step 1 — Build the Container

On the GPU server, inside the `gpu-services/` directory:

```bash
cd gpu-services
docker compose build wan-video
```

The Dockerfile installs PyTorch with CUDA 12.8, HuggingFace `diffusers` (from main branch),
`transformers`, `accelerate`, and all required dependencies.

---

## Step 2 — Start the Service

```bash
docker compose up -d wan-video
```

**On first start**, the container will auto-download the model weights from HuggingFace
(`Wan-AI/Wan2.2-TI2V-5B-Diffusers`, ~20 GB). This only happens once — weights are
cached in the shared `hf-cache` Docker volume.

Monitor the download progress:

```bash
docker compose logs -f wan-video
```

You should see:

```
Loading Wan 2.2 pipeline (model=TI2V-5B) ...
Downloading model ...
Wan 2.2 pipeline loaded in XXXs (model=TI2V-5B, offload=False)
```

---

## Step 3 — Verify

```bash
# Health check
curl http://localhost:3019/health

# List models
curl http://localhost:3019/models
```

Expected health response:

```json
{
  "status": "ok",
  "service": "wan-video-api",
  "gpu_available": true,
  "model_loaded": true,
  "model": "TI2V-5B",
  "offload": false
}
```

---

## Step 4 — Test Generation

```bash
curl -X POST http://localhost:3019/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A cat walking through a garden in golden hour light, cinematic",
    "width": 1280,
    "height": 704,
    "num_frames": 49,
    "num_inference_steps": 30,
    "fps": 24
  }' | python3 -c "
import sys, json, base64
data = json.load(sys.stdin)
with open('test_wan.mp4', 'wb') as f:
    f.write(base64.b64decode(data['video']))
print(f'Saved test_wan.mp4 ({data[\"duration_s\"]}s, {data[\"width\"]}x{data[\"height\"]})')
"
```

> Use `num_frames: 49` and `num_inference_steps: 30` for a fast test (~2s video).
> Full quality: `num_frames: 121` (5s), `num_inference_steps: 50`.

---

## Step 5 — Register as Provider in Bob Manager

In the Bob Manager UI:

1. Go to **Providers** → **Add Provider**
2. Set:
   - **Name**: `wan-video` (or any label)
   - **Type**: `wan_video`
   - **URL**: `http://<GPU_SERVER_IP>:3019`
3. Save

The pipeline is now available as a tool in conversations and labs.

---

## Environment Variables

All configurable via `docker-compose.yml` or `.env`:

| Variable | Default | Description |
|---|---|---|
| `WAN_MODEL` | `TI2V-5B` | Model variant (`TI2V-5B`, `T2V-A14B`, `I2V-A14B`) |
| `WAN_MODEL_DIR` | *(empty)* | Path to pre-downloaded model dir (skip HF download) |
| `WAN_OFFLOAD` | `auto` | CPU offload: `auto` (offload if VRAM < 30GB), `always`, `never` |
| `WAN_IDLE_UNLOAD_SEC` | `600` | Seconds of idle before unloading model from VRAM |
| `WAN_HOST` | `0.0.0.0` | API bind address |
| `WAN_PORT` | `3019` | API port |

---

## Pre-downloading Models (Optional)

If you prefer to download models before building/starting the container:

```bash
# TI2V-5B (~20 GB)
huggingface-cli download Wan-AI/Wan2.2-TI2V-5B-Diffusers --local-dir ./models/wan-video

# Then set in docker-compose or .env:
# WAN_MODEL_DIR=/models/wan-video
```

And add a volume mount in `docker-compose.yml`:

```yaml
volumes:
  - ./models/wan-video:/models/wan-video
```

---

## Using the A14B Models (Advanced)

For higher quality with a bigger GPU (80 GB+), use the MoE 14B-active models:

```bash
# Text-to-video (A14B MoE)
WAN_MODEL=T2V-A14B docker compose up -d wan-video

# Image-to-video (A14B MoE)
WAN_MODEL=I2V-A14B docker compose up -d wan-video
```

These models auto-download (~50 GB each). They produce better results but require
significantly more VRAM. With `WAN_OFFLOAD=always`, they can run on 32 GB GPUs
at the cost of slower generation.

---

## Troubleshooting

### OOM (Out of Memory)

```
torch.OutOfMemoryError: CUDA out of memory
```

**Fix**: Set `WAN_OFFLOAD=always` in docker-compose to move sub-models to CPU when not active:

```yaml
environment:
  WAN_OFFLOAD: always
```

### Container exits immediately

Check logs:

```bash
docker compose logs wan-video
```

Common causes:
- Missing `nvidia-container-toolkit` → install it and restart Docker
- GPU driver mismatch → ensure CUDA 12.x drivers are installed

### Slow first generation

Normal — the model loads on first request (lazy loading). Subsequent generations
are fast until the idle timeout unloads the model. Increase `WAN_IDLE_UNLOAD_SEC`
to keep the model resident longer.

### Model download stuck / fails

If HuggingFace download is slow or fails:

```bash
# Pre-download on the host, then mount as volume
huggingface-cli download Wan-AI/Wan2.2-TI2V-5B-Diffusers --local-dir ./models/wan-video
```

Then set `WAN_MODEL_DIR=/models/wan-video` and add the volume mount.
