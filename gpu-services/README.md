# GPU Services

Standalone FastAPI services for GPU-accelerated media generation. Each service runs independently with its own venv and systemd unit.

## Services

| Service | Port | Description | Model |
|---------|------|-------------|-------|
| **musicgen-api** | 3014 | Text-to-music generation | Meta AudioCraft MusicGen |
| **bark-api** | 3015 | Text-to-speech / singing | Suno Bark |
| **rvc-api** | 3016 | Voice conversion | RVC (Retrieval-based VC) |
| **coqui-tts-api** | 3017 | Text-to-speech + voice cloning | CoquiTTS XTTS v2 |
| **comfyui** | 8188 | Generative image/video graph runtime (host install) | Operator-managed model zoo |

## ComfyUI (host install)

ComfyUI is installed separately from the multi-service `install.sh` because it
manages its own model zoo (checkpoints, LoRAs, VAEs, ControlNets, ...). See
[comfyui/README.md](comfyui/README.md). Quick install:

```bash
cd gpu-services/comfyui
sudo bash install.sh                # default: port 8188, /opt/comfyui, cu121
sudo bash install.sh --port 8190 --cuda cu124
```

After install, register an `AIProvider` in Bob UI with type `comfyui` and
`base_url=http://<host>:8188`. The control plane's `comfyui` tool will route
through it.

## Installation (systemd)

```bash
# Copy gpu-services/ to the GPU server, then:
cd gpu-services/

# Install a single service
sudo bash install.sh musicgen

# Install multiple
sudo bash install.sh musicgen bark

# Install all
sudo bash install.sh all
```

### Environment variables

Set before running `install.sh` to customize:

| Variable | Default | Description |
|----------|---------|-------------|
| `HF_TOKEN` | — | HuggingFace token for gated models |
| `MUSICGEN_MODEL` | `medium` | MusicGen variant: small/medium/large/melody |
| `MUSICGEN_MAX_DURATION_SEC` | `30` | Max generation duration |
| `MUSICGEN_IDLE_UNLOAD_SEC` | `300` | Unload model after N seconds idle |
| `BARK_IDLE_UNLOAD_SEC` | `300` | Unload Bark after N seconds idle |
| `RVC_MODELS_DIR` | `/opt/bob-rvc-models` | Directory for RVC .pth + .index files |

## Management

```bash
# Status
systemctl status bob-musicgen-api

# Logs
journalctl -u bob-musicgen-api -f

# Restart
sudo systemctl restart bob-musicgen-api

# Uninstall
sudo bash install.sh --uninstall musicgen
sudo bash install.sh --uninstall all
```

## API Endpoints

### MusicGen (port 3014)
- `GET /health` — Health check + GPU info
- `POST /generate` — Generate music from text prompt
  ```json
  {
    "prompt": "upbeat electronic dance music with synths",
    "duration": 15,
    "model": "medium",
    "temperature": 1.0,
    "top_k": 250
  }
  ```

### Bark (port 3015)
- `GET /health` — Health check + GPU info
- `POST /generate` — Generate speech/singing from text
  ```json
  {
    "prompt": "♪ Hello world, this is a song ♪",
    "speaker": "v2/en_speaker_6",
    "temperature": 0.7
  }
  ```

### RVC (port 3016)
- `GET /health` — Health check + loaded models
- `GET /models` — List available voice models
- `POST /infer` — Convert voice in audio
  ```json
  {
    "audio": "<base64 WAV>",
    "model_name": "my_voice_model",
    "pitch_shift": 0,
    "f0_method": "rmvpe"
  }
  ```

### CoquiTTS (port 3017)
- `GET /health` — Health check + available speakers
- `GET /speakers` — List pre-saved speaker voices
- `POST /generate` — Generate speech from text with voice cloning
  ```json
  {
    "prompt": "Hello, this is a test of voice cloning.",
    "language": "en",
    "speaker_name": "my_voice",
    "speed": 1.0,
    "temperature": 0.65
  }
  ```

## Docker Compose (recommended)

```bash
cd gpu-services/

# Start all services
docker compose up -d

# Start a single service
docker compose up -d musicgen

# View logs
docker compose logs -f

# Rebuild after updates
docker compose up -d --build
```

### RVC voice models

Place `.pth` and `.index` files in `gpu-services/models/rvc/` on the host:

```
gpu-services/
  models/
    rvc/
      my_voice.pth
      my_voice.index      # optional, improves quality
      another_voice.pth
```

Models are mounted into the container at `/models` and picked up automatically.
Verify with: `GET http://<host>:3016/models`

### CoquiTTS speaker voices

Place `.wav` reference audio files (~6 seconds each) in `gpu-services/models/speakers/`:

```
gpu-services/
  models/
    speakers/
      my_voice.wav          # ~6s reference audio
      narrator.wav
```

Mounted at `/speakers` in the container. Use the filename (without `.wav`) as `speaker_name` in API calls.
Verify with: `GET http://<host>:3017/speakers`

### Override defaults

Create a `.env` file next to `docker-compose.yml`:

```env
MUSICGEN_MODEL=large
MUSICGEN_MAX_DURATION_SEC=60
MUSICGEN_IDLE_UNLOAD_SEC=600
BARK_IDLE_UNLOAD_SEC=600
RVC_IDLE_UNLOAD_SEC=600
COQUI_IDLE_UNLOAD_SEC=600
```

## Docker (manual)

Each service also has a standalone Dockerfile:

```bash
cd musicgen-api
docker build -t bob-musicgen-api .
docker run --gpus all -p 3014:3014 bob-musicgen-api
```

## VRAM Requirements

| Service | Small | Medium | Large |
|---------|-------|--------|-------|
| MusicGen | ~2 GB | ~4 GB | ~8 GB |
| Bark | ~5 GB | — | — |
| RVC | ~2 GB per model | — | — |
| CoquiTTS | ~4 GB | — | — |

All services auto-unload models after idle timeout to free VRAM.
