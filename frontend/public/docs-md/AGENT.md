# Bob Labs — Agent Architecture

## Overview

The Bob Labs Agent is a lightweight daemon that runs on each GPU/compute server. It maintains a persistent WebSocket connection to one or more control planes, reporting hardware metrics, executing remote commands, and providing access to GPU pipeline services.

**Source directory:** `agent/`

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  GPU Server                                              │
│                                                          │
│  ┌────────────────────────────────────────┐              │
│  │  Bob Agent (Python 3.10+)              │              │
│  │                                        │              │
│  │  ┌────────────┐  ┌─────────────────┐  │              │
│  │  │ Collectors  │  │  WebSocket      │  │              │
│  │  │ • CPU       │  │  Client(s)      │──┼──► Control   │
│  │  │ • Memory    │  │  (one per CP)   │  │    Plane(s)  │
│  │  │ • Disk      │  │                 │  │    :8888     │
│  │  │ • GPU       │  └─────────────────┘  │              │
│  │  │ • Network   │                       │              │
│  │  │ • Docker    │  ┌─────────────────┐  │              │
│  │  │ • Process   │  │  Prometheus     │  │              │
│  │  └────────────┘  │  Metrics :9100   │  │              │
│  │                   └─────────────────┘  │              │
│  │  ┌────────────┐                        │              │
│  │  │ Inspectors │  ┌─────────────────┐  │              │
│  │  │ • Hardware  │  │  Executor       │  │              │
│  │  │ • Services  │  │  (commands)     │  │              │
│  │  └────────────┘  └─────────────────┘  │              │
│  └────────────────────────────────────────┘              │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  GPU Services (separate processes)                   │ │
│  │  MusicGen:3014  Bark:3015  RVC:3016  CoquiTTS:3017  │ │
│  │  STT:7865  LTX-Video:3018  Wan-Video:3019           │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌───────────────┐  ┌──────────────────┐                 │
│  │ Script Runner  │  │  Ollama / vLLM   │                 │
│  │ :9101          │  │  (LLM serving)   │                 │
│  └───────────────┘  └──────────────────┘                 │
└─────────────────────────────────────────────────────────┘
```

## Components

### Collectors (`agent/app/collectors/`)

Periodically gather system metrics:

| Collector | Data |
|-----------|------|
| CPU | Usage percentage, core count, temperatures |
| Memory | Total, used, available, swap |
| Disk | Partition usage, I/O stats |
| GPU | NVIDIA GPU utilization, VRAM, temperature, power (via nvidia-smi / pynvml) |
| Network | Interface speeds, bytes in/out |
| Docker | Running containers, resource usage |
| Process | Top processes by CPU/memory |

Metrics are sent to the control plane at the configured `METRICS_INTERVAL` (default: 10 seconds) and exposed as Prometheus metrics on `METRICS_PORT` (default: 9100).

### Inspectors (`agent/app/inspectors/`)

Provide on-demand hardware and service inspection data when queried by the control plane.

### Executor (`agent/app/executor/`)

Handles remote command execution requests from the control plane. Commands are received via WebSocket and executed on the host.

### WebSocket Client (`agent/app/websocket/`)

Maintains a persistent WebSocket connection to the control plane. Handles:

- **Authentication** — Sends `AGENT_SECRET` on connect
- **Heartbeat** — Periodic ping at `HEARTBEAT_INTERVAL` (default: 30 seconds)
- **Metrics** — Pushes collector data at `METRICS_INTERVAL`
- **Commands** — Receives and executes remote commands
- **Reconnection** — Automatic reconnect with backoff on disconnect

### Multi-Control-Plane Support

The agent can connect to **multiple control planes simultaneously** by providing comma-separated URLs:

```env
CONTROL_PLANE_URL=ws://192.168.1.101:8888/ws/agent,ws://192.168.1.102:8888/ws/agent
```

One `AgentWebSocketClient` instance is created per URL. All clients share the same collectors and executor. This allows a single GPU server to report to both production and development control planes.

## Installation

### systemd (Recommended for bare metal)

```bash
# On the GPU server
cd bob-manager/agent
sudo bash install.sh
```

This script:
1. Creates a `bob-agent` system user (with `video` + `docker` groups)
2. Installs the agent to `/opt/bob-agent/`
3. Creates a Python virtual environment with dependencies
4. Creates `/etc/bob-agent.env` configuration file
5. Installs and enables a systemd service

**Configure:**
```bash
sudo nano /etc/bob-agent.env
```

```env
AGENT_USER=bob-agent
AGENT_NAME=gpu-server-01
CONTROL_PLANE_URL=ws://192.168.1.101:8888/ws/agent
AGENT_SECRET=<must-match-control-plane>
METRICS_PORT=9100
HEARTBEAT_INTERVAL=30
METRICS_INTERVAL=10
```

**Start:**
```bash
sudo systemctl start bob-agent
sudo systemctl status bob-agent
journalctl -fu bob-agent
```

### Docker

```bash
cd bob-manager
docker compose -f docker-compose.agent.yml up -d
```

Or build manually:
```bash
cd agent
docker build -t bob-agent .
docker run -d --name bob-agent \
  -e AGENT_NAME=gpu-server-01 \
  -e CONTROL_PLANE_URL=ws://control-plane:8888/ws/agent \
  -e AGENT_SECRET=your-secret \
  -p 9100:9100 \
  bob-agent
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_NAME` | `gpu-server` | Display name in the control plane UI |
| `CONTROL_PLANE_URL` | `ws://localhost:8000/ws/agent` | WebSocket URL(s), comma-separated for multi-plane |
| `AGENT_SECRET` | `change-this-to-a-random-secret-token` | Must match control plane `AGENT_SECRET` |
| `METRICS_PORT` | `9100` | Prometheus metrics endpoint port |
| `HEARTBEAT_INTERVAL` | `30` | Seconds between heartbeat pings |
| `METRICS_INTERVAL` | `10` | Seconds between metric collection/push |
| `SCRIPT_RUNNER_URL` | `http://localhost:9101` | Script runner service for custom scripts |
| `MUSICGEN_URL` | `http://localhost:3014` | MusicGen API endpoint |
| `BARK_URL` | `http://localhost:3015` | Bark API endpoint |
| `RVC_URL` | `http://localhost:3016` | RVC API endpoint |
| `COQUI_TTS_URL` | `http://localhost:3017` | CoquiTTS API endpoint |
| `STT_URL` | `http://localhost:7865` | STT API endpoint |
| `LTX_VIDEO_URL` | `http://localhost:3018` | LTX-Video API endpoint |
| `WAN_VIDEO_URL` | `http://localhost:3019` | Wan-Video API endpoint |

## WebSocket Protocol

### Connection

```
Agent → ws://control-plane:8888/ws/agent
        Header: Authorization: Bearer <AGENT_SECRET>
```

### Message Types

| Direction | Type | Payload | Description |
|-----------|------|---------|-------------|
| Agent → CP | `register` | `{name, version}` | Initial registration |
| Agent → CP | `heartbeat` | `{timestamp}` | Keep-alive ping |
| Agent → CP | `metrics` | `{cpu, memory, gpu, disk, ...}` | System metrics push |
| CP → Agent | `command` | `{id, command, args}` | Execute a command |
| Agent → CP | `command_result` | `{id, output, exit_code}` | Command result |

### Connection Lifecycle

```
1. Connect to WebSocket endpoint
2. Send AGENT_SECRET in header
3. Control plane validates → registers server
4. Agent starts heartbeat + metrics loops
5. On disconnect → exponential backoff reconnect
```

## Script Runner

The optional Script Runner service (`script-runner/`) extends the agent with custom script execution:

- Runs at port 9101
- Accepts scripts from the control plane
- Executes in an isolated environment
- Returns stdout/stderr

See `script-runner/README.md` for details.

## Related Documents

- [GPU_SERVICES.md](GPU_SERVICES.md) — GPU pipeline services
- [ARCHITECTURE.md](ARCHITECTURE.md) — System architecture overview
- [CONFIGURATION.md](CONFIGURATION.md) — All environment variables
- [INSTALL_PROD.md](INSTALL_PROD.md) — Production deployment guide
