# Bob Script Runner

GPU-side service that exposes heavy model scripts (audio generation, video, TTS, etc.) as HTTP endpoints for the Bob Manager control plane.

Default port: **9101** (9100 is used by the agent metrics exporter).

## Architecture

```
GPU Server                          Control Plane
┌─────────────────────┐            ┌───────────────────────┐
│  bob-agent           │  WS push  │  agent_handler.py     │
│  ├─ probes runner    │──────────►│  caches scripts in hub│
│  └─ sends scripts    │           │                       │
│                      │           │  tool_executor.py     │
│  bob-script-runner   │  HTTP     │  audio_generate tool  │
│  (FastAPI, port 9101)│◄──────────│  routes to runner     │
│                      │           │                       │
│  /opt/bob-scripts/   │  output   │  Lab Agent calls:     │
│  ├── riffusion.py    │──────────►│  audio_generate(...)  │
│  ├── stable_audio.py │  (base64) │                       │
│  └── musicgen.py     │           │                       │
└─────────────────────┘            └───────────────────────┘
```

The bob-agent on each GPU server auto-discovers the local script runner and pushes
available scripts to the control plane via WebSocket (same as Ollama model discovery).
No manual URL configuration is needed on the control plane.

## Installation

On each GPU server:

```bash
cd /path/to/bob-manager/script-runner
sudo bash install.sh
```

This will:
1. Create `/opt/bob-scripts/` directory for scripts
2. Install the runner service at `/opt/bob-script-runner/`
3. Create and start a systemd service `bob-script-runner`

Copy example scripts:
```bash
sudo cp scripts/*.py /opt/bob-scripts/
```

## Configuration

Environment variables (set in systemd unit or before running):

| Variable | Default | Description |
|----------|---------|-------------|
| `BOB_SCRIPTS_DIR` | `/opt/bob-scripts` | Directory to scan for scripts |
| `BOB_SCRIPTS_PORT` | `9101` | HTTP port |
| `BOB_SCRIPTS_OUTPUT` | `/tmp/bob-script-output` | Temp dir for output files |
| `BOB_SCRIPTS_MAX_OUTPUT_MB` | `100` | Max total output size per run |

## Writing Scripts

Each script is a Python file in `/opt/bob-scripts/` with:

1. A `BOB_SCRIPT_META` JSON block in the docstring
2. A `run(args, output_dir)` function

### Template

```python
"""My Custom Model — description.

BOB_SCRIPT_META:
{
  "name": "my_model",
  "description": "What this script does",
  "env": "conda:my_conda_env",
  "parameters": {
    "prompt": {"type": "string", "description": "Input prompt", "required": true},
    "option": {"type": "integer", "description": "Some option", "required": false}
  }
}

"""

import os

def run(args: dict, output_dir: str) -> dict:
    prompt = args.get("prompt", "")
    if not prompt:
        return {"success": False, "message": "Missing prompt"}

    # ... do work, save files to output_dir ...
    out_path = os.path.join(output_dir, "result.wav")

    return {
        "success": True,
        "message": "Done",
        "files": ["result.wav"],  # filenames in output_dir
    }
```

### Convention

- `args`: dict of parameters from the tool call
- `output_dir`: temp directory where output files should be saved
- Return dict with `success`, `message`, and optionally `files` (list of filenames)
- The runner collects files from `output_dir`, base64-encodes them, and returns to the control plane
- The control plane saves them to the lab's workspace

### Virtual Environment Support

Each script can specify its own Python environment via the `env` field in `BOB_SCRIPT_META`:

| Format | Example | Resolved interpreter |
|--------|---------|---------------------|
| `conda:<name>` | `"env": "conda:riffusion_old"` | `conda run --no-capture-output -n riffusion_old python` |
| venv path | `"env": "/path/to/.venv"` | `/path/to/.venv/bin/python` |
| python path | `"env": "/usr/bin/python3.11"` | `/usr/bin/python3.11` |
| *(omitted)* | — | System `python3` |

Scripts are executed as **subprocesses** using the resolved interpreter, so each script runs with its own dependencies.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/scripts` | List available scripts + metadata |
| POST | `/scripts/{name}/run` | Execute a script |

### Example

```bash
# List scripts
curl http://gpu-server:9101/scripts

# Run riffusion
curl -X POST http://gpu-server:9101/scripts/riffusion/run \
  -H "Content-Type: application/json" \
  -d '{"arguments": {"prompt": "upbeat electronic track", "duration_sec": 10}}'
```

## Available Scripts

| Script | Model | Description |
|--------|-------|-------------|
| `riffusion.py` | riffusion/riffusion-model-v1 | Spectrogram-based music generation |
| `stable_audio.py` | stabilityai/stable-audio-open-1.0 | Stable Audio Open for music/SFX |
| `musicgen.py` | facebook/musicgen-{small,medium,large} | Meta's MusicGen text-to-music |

## Control Plane Integration

No manual configuration needed. The bob-agent on each GPU server:

1. Probes the local script runner at `SCRIPT_RUNNER_URL` (default `http://localhost:9101`)
2. Fetches the list of available scripts (GET `/scripts`)
3. Pushes the scripts to the control plane via WebSocket (on registration + periodic metrics)
4. The control plane caches available scripts per agent in the WebSocket hub
5. When a lab calls `audio_generate`, the control plane routes to the right agent's runner

### Agent Configuration

Set on the bob-agent (on the GPU server):

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRIPT_RUNNER_URL` | `http://localhost:9101` | Local script runner URL |

Lab agents can then use the `audio_generate` tool:
```
<tool_call>{"name": "audio_generate", "arguments": {"script": "riffusion", "prompt": "calm piano melody", "duration_sec": 15}}</tool_call>
```
