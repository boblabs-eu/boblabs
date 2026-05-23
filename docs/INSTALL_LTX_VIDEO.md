# LTX-Video Installation Guide

One-shot guide to deploy LTX-2.3 (22B DiT text/image → video) on a GPU server.

## Prerequisites

| Requirement | Minimum |
|---|---|
| GPU | NVIDIA with **32 GB+ VRAM** (RTX 5090, A100-40G, etc.) |
| System RAM | 30 GB + **32 GB swap** (needed for mmap of 43 GB checkpoint) |
| Disk | ~70 GB free (models ~50 GB + Docker image ~20 GB) |
| Docker | Docker Engine 24+ with `docker compose` v2 |
| NVIDIA runtime | `nvidia-container-toolkit` installed and configured |
| HuggingFace account | Required — Gemma 3 12B is a **gated model** |

---

## Step 1 — Add Swap (if < 64 GB RAM)

The 22B distilled checkpoint is 43 GB on disk. Safetensors uses `mmap()` to map
it into virtual memory before streaming tensors to GPU. If your total virtual
memory (RAM + swap) is less than 43 GB, the kernel will refuse the mapping.

```bash
sudo fallocate -l 32G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Verify: `free -h` should show 30+ GB swap.

---

## Step 2 — HuggingFace Account & Gemma Access

LTX-2.3 uses **Google Gemma 3 12B** as its text encoder. This is a gated model
that requires you to accept Google's license on HuggingFace.

### 2a. Create a HuggingFace account
Go to https://huggingface.co/join and create an account.

### 2b. Accept the Gemma license
1. Go to https://huggingface.co/google/gemma-3-12b-it-qat-q4_0-unquantized
2. Click **"Agree and access repository"**
3. Wait for approval (usually instant)

### 2c. Create an access token
1. Go to https://huggingface.co/settings/tokens
2. Click **"New token"** → name it (e.g., "gpu-server") → role: **Read**
3. Copy the token (starts with `hf_...`)

### 2d. Login on the server
```bash
pip install huggingface_hub[cli]   # or: pipx install huggingface_hub[cli]
hf auth login
# Paste your token when prompted
```

---

## Step 3 — Download Model Files

Navigate to the gpu-services directory:
```bash
cd ~/bob-manager/gpu-services
```

### 3a. Download LTX-2.3 checkpoints (~45 GB)

Only the distilled pipeline files are needed:
```bash
hf download Lightricks/LTX-2.3 \
    --include "ltx-2.3-22b-distilled-1.1.safetensors" \
    --include "ltx-2.3-spatial-upscaler-x2-1.1.safetensors" \
    --include "ltx-2.3-22b-distilled-lora-384-1.1.safetensors" \
    --local-dir ./models/ltx-video
```

### 3b. Download Gemma 3 12B text encoder (~24 GB)
```bash
hf download google/gemma-3-12b-it-qat-q4_0-unquantized \
    --local-dir ./models/gemma
```

### 3c. Fix permissions (if needed)
```bash
sudo chown -R $(whoami) ./models
```

### 3d. Verify files
```bash
ls -lh ./models/ltx-video/*.safetensors
# Should show 3 files (~43GB + ~400MB + ~400MB)

ls ./models/gemma/tokenizer.model
# Should exist
```

---

## Step 4 — Build & Start the Container

```bash
cd ~/bob-manager/gpu-services
docker compose up -d --build ltx-video
```

Watch the build (first build takes ~10 min to clone LTX-2 repo and install deps):
```bash
docker compose logs -f ltx-video
```

Wait for:
```
INFO:     Uvicorn running on http://0.0.0.0:3018
```

---

## Step 5 — Verify

### Health check
```bash
curl http://localhost:3018/health | python3 -m json.tool
```

Expected:
```json
{
    "status": "ok",
    "gpu_available": true,
    "model_loaded": false,
    "pipeline_mode": "distilled"
}
```

### Test generation (first run loads model — may take 1-2 min)
```bash
curl -X POST http://localhost:3018/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "A golden retriever running on a beach at sunset, cinematic lighting, 4K"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Duration: {d[\"duration_s\"]}s, Size: {len(d[\"video\"])//1024}KB')"
```

---

## Step 6 — Register as AI Provider in Bob Manager

1. Open Bob Manager UI → **Orchestrator** → **Models** tab
2. Click **Add Provider**
3. Fill in:
   - **Name**: LTX-Video
   - **Type**: `ltx_video`
   - **Base URL**: `http://<gpu-server-ip>:3018`
   - **Server**: select your GPU server
4. Save — the model will appear in the provider list

---

## Environment Variables (Optional)

Set these in a `.env` file next to `docker-compose.yml` or via `environment:` in the compose file:

| Variable | Default | Description |
|---|---|---|
| `LTX_PIPELINE_MODE` | `distilled` | Pipeline mode: `distilled`, `two_stage`, `two_stage_hq` |
| `LTX_QUANTIZATION` | `fp8-cast` | DiT quantization: `none`, `fp8-cast`, `fp8-scaled-mm` |
| `LTX_IDLE_UNLOAD_SEC` | `600` | Seconds idle before unloading model from VRAM |
| `LTX_STREAMING_PREFETCH` | `0` | Layer streaming prefetch count (0 = disabled, needs 64GB+ RAM) |

---

## Troubleshooting

### `FileNotFoundError: tokenizer.model not found under /models/gemma`
Gemma files not downloaded. Re-run step 3b. Ensure you accepted the Gemma license (step 2b).

### `Access denied. This repository requires approval`
You haven't accepted the Gemma license or aren't logged in. Run `hf auth login` and visit the Gemma model page to accept.

### `RuntimeError: unable to mmap 46149345334 bytes — Cannot allocate memory`
Not enough virtual memory. Add swap (step 1). The kernel needs RAM+swap ≥ 43 GB.

### `torch.OutOfMemoryError: CUDA out of memory`
- Ensure `LTX_QUANTIZATION=fp8-cast` is set (reduces DiT from bf16 to fp8)
- Ensure `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` is set
- The code wraps generation in `torch.inference_mode()` automatically

### Container killed silently (no traceback, just restarts)
Kernel OOM killer hit the container. Check `dmesg | grep -i oom`. Add more swap.

### Permission errors on `./models/gemma/.cache`
```bash
sudo chown -R $(whoami) ./models
```
