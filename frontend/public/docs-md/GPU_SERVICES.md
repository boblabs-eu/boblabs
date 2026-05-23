# Bob Labs — GPU Services

Standalone FastAPI services for GPU-accelerated media generation. Each service runs independently with its own virtual environment and systemd unit (or Docker container).

## Service Inventory

| Service | Port | Model | VRAM | Description |
|---------|------|-------|------|-------------|
| **MusicGen** | 3014 | Meta AudioCraft MusicGen | ~4-8 GB | Text-to-music instrumental generation |
| **Bark** | 3015 | Suno Bark | ~5 GB | Text-to-speech and singing (♪ tokens) |
| **RVC** | 3016 | Retrieval-based Voice Conversion | ~2 GB | Voice conversion with custom voice models |
| **CoquiTTS** | 3017 | XTTS v2 | ~4 GB | Text-to-speech with voice cloning |
| **STT** | 7865 | OpenAI Whisper | ~4 GB | Speech-to-text transcription |
| **LTX-Video** | 3018 | LTX-Video | ~12 GB | Text/image to video generation |
| **Wan-Video** | 3019 | Wan-Video | ~14 GB | Text/image to video generation |

All services auto-unload models from VRAM after a configurable idle timeout.

## Installation

### Docker Compose (Recommended)

```bash
cd gpu-services/

# Start all services
docker compose up -d

# Start a specific service
docker compose up -d musicgen bark

# View logs
docker compose logs -f musicgen

# Rebuild after updates
docker compose up -d --build
```

**Prerequisite:** NVIDIA GPU with [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) installed.

### systemd (Bare Metal)

```bash
cd gpu-services/

# Install a single service
sudo bash install.sh musicgen

# Install multiple
sudo bash install.sh musicgen bark rvc

# Install all
sudo bash install.sh all

# Uninstall
sudo bash install.sh --uninstall musicgen
sudo bash install.sh --uninstall all
```

### Management

```bash
# Status
systemctl status bob-musicgen-api

# Logs
journalctl -u bob-musicgen-api -f

# Restart
sudo systemctl restart bob-musicgen-api
```

## API Reference

### MusicGen (port 3014)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check + GPU info |
| `/generate` | POST | Generate music from text prompt |

```json
POST /generate
{
  "prompt": "upbeat electronic dance music with synths",
  "duration": 15,
  "model": "medium",
  "temperature": 1.0,
  "top_k": 250
}
```

Supports melody conditioning and audio continuation via optional `continuation_audio` and `melody_audio` base64 fields.

### Bark (port 3015)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check + GPU info |
| `/generate` | POST | Generate speech or singing |

```json
POST /generate
{
  "prompt": "♪ Hello world, this is a song ♪",
  "speaker": "v2/en_speaker_6",
  "temperature": 0.7
}
```

Use `♪` tokens around text for singing, `[laughs]`, `[sighs]` for effects.

### RVC (port 3016)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check + loaded models |
| `/models` | GET | List available voice models |
| `/infer` | POST | Convert voice in audio |

```json
POST /infer
{
  "audio": "<base64 WAV>",
  "model_name": "my_voice_model",
  "pitch_shift": 0,
  "f0_method": "rmvpe"
}
```

Parameters: `pitch_shift` (-12 to +12 semitones), `filter_radius`, `index_ratio`, `rms_mix_rate`, `protect`, `f0_method` (rmvpe, crepe, harvest, pm).

### CoquiTTS (port 3017)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check + available speakers |
| `/speakers` | GET | List pre-saved speaker voices |
| `/generate` | POST | Generate speech with voice cloning |

```json
POST /generate
{
  "prompt": "Hello, this is a test of voice cloning.",
  "language": "en",
  "speaker_name": "my_voice",
  "speed": 1.0,
  "temperature": 0.65
}
```

### STT (port 7865)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/transcribe` | POST | Transcribe audio to text |

### LTX-Video (port 3018)

See [INSTALL_LTX_VIDEO.md](INSTALL_LTX_VIDEO.md) for detailed setup instructions.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/generate` | POST | Generate video from text/image |

### Wan-Video (port 3019)

See [INSTALL_WAN_VIDEO.md](INSTALL_WAN_VIDEO.md) for detailed setup instructions.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/generate` | POST | Generate video from text/image |

## Voice Models & Speaker References

### RVC Voice Models

Place `.pth` and optional `.index` files in `gpu-services/models/rvc/`:

```
gpu-services/models/rvc/
  my_voice.pth          # Required: trained voice model
  my_voice.index        # Optional: improves quality
  another_voice.pth
```

Mounted at `/models` in the container. Verify with `GET http://<host>:3016/models`.

### CoquiTTS Speaker Voices

Place `.wav` reference audio files (~6 seconds each) in `gpu-services/models/speakers/`:

```
gpu-services/models/speakers/
  my_voice.wav          # ~6s reference audio for cloning
  narrator.wav
```

Mounted at `/speakers` in the container. Use filename (without `.wav`) as `speaker_name`. Verify with `GET http://<host>:3017/speakers`.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HF_TOKEN` | — | HuggingFace token for gated model downloads |
| `MUSICGEN_MODEL` | `medium` | MusicGen variant: small, medium, large, melody |
| `MUSICGEN_MAX_DURATION_SEC` | `30` | Maximum generation duration |
| `MUSICGEN_IDLE_UNLOAD_SEC` | `300` | Unload model after N seconds idle |
| `BARK_IDLE_UNLOAD_SEC` | `300` | Bark idle unload timeout |
| `RVC_MODELS_DIR` | `/opt/bob-rvc-models` | RVC voice model directory |
| `RVC_IDLE_UNLOAD_SEC` | `300` | RVC idle unload timeout |
| `COQUI_IDLE_UNLOAD_SEC` | `300` | CoquiTTS idle unload timeout |

Create a `.env` file next to `gpu-services/docker-compose.yml` to override defaults.

### VRAM Budget

On a single GPU (e.g., RTX 3090 24 GB):

| Service | At Rest | During Inference |
|---------|---------|-----------------|
| MusicGen (medium) | ~0 GB (load on demand) | ~4-8 GB |
| Bark | ~0 GB (load on demand) | ~5 GB |
| RVC | ~0 GB (load on demand) | ~2 GB |
| CoquiTTS | ~0 GB (load on demand) | ~4 GB |
| STT | ~0 GB (load on demand) | ~4 GB |
| LTX-Video | ~0 GB (load on demand) | ~12 GB |
| Wan-Video | ~0 GB (load on demand) | ~14 GB |

**Strategy:** Models are loaded on demand and unloaded after the idle timeout. The agent calls pipelines sequentially, so only one heavy model is active at a time.

For multiple GPU servers, distribute services:
```
GPU Server A (24 GB): musicgen + bark + rvc + coqui-tts
GPU Server B (24 GB): ltx-video + wan-video + stt
```

## Integration with Bob Labs

GPU services integrate with the platform through the **media pipeline** system:

1. Each service is registered as an `AIProvider` in Bob Labs with the matching `provider_type`
2. The `media_pipeline` tool routes to the correct service via the dispatcher
3. The agent orchestrates multi-stage workflows (e.g., MusicGen → Bark → RVC → audio_mix)
4. All pipeline calls use the standard load-balanced routing with failover

See [MUSIC_PIPELINES.md](MUSIC_PIPELINES.md) for the full multi-pipeline song generation architecture.

## Related Documents

- [MUSIC_PIPELINES.md](MUSIC_PIPELINES.md) — Song generation pipeline architecture
- [INSTALL_LTX_VIDEO.md](INSTALL_LTX_VIDEO.md) — LTX-Video installation guide
- [INSTALL_WAN_VIDEO.md](INSTALL_WAN_VIDEO.md) — Wan-Video installation guide
- [CONFIGURATION.md](CONFIGURATION.md) — Environment variable reference
- [AGENT.md](AGENT.md) — Agent setup (connects GPU services to control plane)
