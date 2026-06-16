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

## Security Posture (operator-facing)

### A04 — Agent runs as `bob-agent` in the `docker` group

`install.sh` creates the `bob-agent` system user and adds it to both
`video` (for nvidia-uvm access) and `docker`. **Membership in `docker`
is root-equivalent**: anyone (or anything) running as `bob-agent` can
`docker run --privileged -v /:/host alpine chroot /host bash` and own
the entire box.

This is an intentional trade-off — the agent reports container metrics
via `docker stats` and lists containers via the Docker socket, both of
which need this privilege. Pretending it's not root would be worse than
documenting it loudly:

* **Threat model**: trust the operator's GPU server posture. Anyone
  with shell access to the GPU box already has root via `docker`; the
  agent doesn't widen the attack surface beyond what a logged-in admin
  already had.
* **Lateral-movement gate**: the agent never executes user-supplied
  shell directly. The only remote command channel is the control-plane
  WebSocket, gated by `AGENT_SECRET`. Rotate `AGENT_SECRET` on suspected
  control-plane compromise.
* **Hardening alternatives if you need to drop `docker` group access**:
  - Run the agent under a **rootless docker** install — owns its own
    daemon socket, no host access.
  - Skip the Docker collector (`AGENT_DISABLE_DOCKER_COLLECTOR=1`) and
    remove the user from the group; you lose the container view in the
    dashboard but the host stays segregated.
  - Run the agent inside a sidecar container that mounts a
    docker-socket-proxy with `CONTAINERS=1` but every write verb off
    (mirrors the `docker-socket-proxy` posture the control-plane uses
    in compose).

### OP03 — Transport for the agent WebSocket

The default `CONTROL_PLANE_URL=ws://…` is **plaintext**. That is fine
for a private LAN behind the same firewall as the control plane (the
typical home-lab deployment). It is **not** fine the moment the agent
talks to the control plane over an untrusted network — coffee shop
WiFi, a residential ISP backhaul, a separate data center. `AGENT_SECRET`
is sent in the `Authorization` header on connect and can be sniffed
verbatim from a plaintext socket.

For any non-loopback / non-LAN deployment:

1. Terminate TLS in front of the control plane (nginx already does this
   in `INSTALL_PROD.md`'s example, just add `location /ws/agent { … }`
   to the existing TLS server block).
2. Point the agent at the public hostname:
   ```env
   CONTROL_PLANE_URL=wss://your-control-plane.example.com/ws/agent
   ```
3. Set a long random `AGENT_SECRET` (≥40 bytes) and rotate it any time
   you suspect the previous one leaked.

The agent will refuse to upgrade `ws://` ↔ `wss://` silently — it
connects to exactly the scheme you ask for. If you mistype `ws://` to a
TLS-terminated endpoint, the handshake fails closed.

### A10 — GPU-service model integrity

`gpu-services/bark-api` and `gpu-services/rvc-api` `torch.load()` user-
provided `.pth` files. Pickle is RCE on load. Both services now support
operator-pinned SHA-256 checksums:

* **RVC**: drop a sibling `<model>.pth.sha256` file with the expected
  hex digest. Set `RVC_REQUIRE_CHECKSUM=1` to refuse load when the
  sidecar is missing.
* **Bark**: set `BARK_CHECKPOINT_DIR=/path/to/bark/cache` and commit a
  `manifest.sha256` (one `<hash>  <filename>` per line) inside it. Set
  `BARK_REQUIRE_MANIFEST=1` for hard-fail on missing manifest.

Generate digests with `sha256sum model.pth > model.pth.sha256`.

### CSO #3 — Containers now drop to uid 1000 (migration on existing volumes)

All production Dockerfiles now declare `USER 1000` and run as a non-
root user. The Dockerfiles use a conditional `useradd` so they reuse
any pre-existing uid-1000 user (e.g. `node:22-slim` ships `node` at
uid 1000, `ubuntu:24.04`-based images ship `ubuntu`) instead of
failing the build with "UID 1000 is not unique". Services affected:

| Service          | uid  | User name (varies by base image) |
|------------------|------|----------------------------------|
| bob-api          | 1000 | `bobapi` (python:slim — created) |
| sandbox          | 1000 | `sandbox` (python:slim — created)|
| showroom-api     | 1000 | `showroom` (python:slim — created)|
| bob-remotion     | 1000 | `node` (reused from node:slim)   |
| bob-agent        | 1000 | `bobagent` (python:slim — created)|
| RVC/Bark/MusicGen/STT/CoquiTTS | 1000 | `gpu` (cuda:ubuntu22.04 — created) |
| LTX/Wan-video    | 1000 | `ubuntu` (reused from cuda:ubuntu24.04) |

**Fresh deploys:** nothing to do. Each named docker volume inherits
`1000:1000` ownership from the first container that writes to it.

**Existing deploys:** the long-lived named volumes were created when
containers ran as root, so they currently belong to `0:0`. Before
redeploying with the new images, chown them once:

```bash
# Stop the stack so no service holds a file open
docker compose down

# Chown each named volume to uid 1000 via a throwaway alpine container
for vol in bob-manager_lab_resources bob-manager_qdrant_staging bob-manager_app_uploads; do
  docker run --rm -v "$vol":/data alpine:3.20 chown -R 1000:1000 /data
done

# Rebuild with the new Dockerfiles + start
docker compose build
docker compose up -d
```

If you mount `/models` from a host directory into RVC/Bark/Coqui/STT/
MusicGen/LTX/Wan, that host directory needs to be readable by uid
1000 (either world-readable, or `sudo chown -R 1000:1000 /path/to/models`).

The agent container collectors handle `psutil.AccessDenied` gracefully
([ports.py:23](agent/app/inspectors/ports.py#L23), [network.py:52](agent/app/collectors/network.py#L52),
[processes.py:32](agent/app/inspectors/processes.py#L32)), so some
per-process / cross-user metrics from the container variant become
unavailable — expected trade-off for not running the metrics daemon
as root.

### CSO #4 — Secret-at-rest for LLM/MCP credential columns

`ai_providers.api_key` and `mcp_servers.auth_token` are now Fernet-
encrypted at rest under `KEY_ENCRYPTION_SECRET`. A DB backup, replica
stream, or read-only audit dump no longer leaks the operator's LLM
provider wallet.

The column type is bidirectional during rollout — legacy plaintext
rows are detected by the absence of the Fernet `gAAAAA` prefix and
read through as-is until the operator runs the one-shot script:

```bash
# 1. Add KEY_ENCRYPTION_SECRET=<any non-empty string> to the bob-api env
#    (docker-compose / .env / your secrets manager).
# 2. Redeploy bob-api so the new env is picked up.
docker compose up -d bob-api

# 3. One-shot rewrite of every plaintext row to its Fernet form.
docker compose exec bob-api python -m app.scripts.encrypt_secrets

# Sample expected output:
#   ai_providers.api_key: 3 rewritten, 1 skipped
#   mcp_servers.auth_token: 0 rewritten, 0 skipped
#   All target rows encrypted on disk.
```

Once the script reports success, **rotate the secret out of any
plaintext config** — the deployment now strictly needs that exact
secret value to start, so losing it bricks the LLM dispatcher.

Rotation (changing `KEY_ENCRYPTION_SECRET`) is not yet supported —
do not change it after the first rewrite without a dedicated re-
encrypt-under-new-key path.

### CSO #5 — Default JWT lifetime dropped to 60 minutes

`JWT_EXPIRE_MINUTES` default changed from 1440 (24h) to 60 (1h) to
shrink the impact window of a leaked token. Operators who want
the legacy 24h window can set the env var explicitly. A separate
follow-up will add refresh-token rotation so the shorter access-
token lifetime doesn't bite the UX.

### CSO #8 — Per-sandbox HMAC + lab-id binding

All per-lab sandbox containers used to share `bob-manager_bob-network`
with no authentication; an attacker who achieved RCE inside any
sandbox could hit any other sandbox at `http://bob-lab-<other_uuid>:9000`
and execute code in its workspace. Two locks now apply:

1. **HMAC-SHA256** signatures on every control-plane → sandbox
   request, under shared `SANDBOX_HMAC_SECRET`. Signature window
   is 60 seconds; replay outside it is rejected.
2. **Per-container lab-id binding** — each sandbox now starts with
   `SANDBOX_LAB_ID=<lab_id>` in its env (passed by
   [container_manager.py](../control-plane/app/services/container_manager.py))
   and rejects any request whose body `lab_id` doesn't match.

To roll out: set `SANDBOX_HMAC_SECRET=<random 32+ char string>` in
the bob-api env, redeploy bob-api, and let lab runs spin up new
sandboxes naturally (they'll inherit the secret). Existing in-flight
sandboxes from before the redeploy stay in legacy unsigned mode
until they're recycled; `docker compose down sandbox && docker
compose up -d` (or `make smoke`-like) recycles them all immediately.

Empty `SANDBOX_HMAC_SECRET` keeps the legacy unsigned behavior so
the rollout doesn't require a flag-day.

## Troubleshooting

### Models not showing in the orchestrator console

The agent connects, the server appears in the dashboard, the agent's
logs show `httpx HTTP Request: GET http://localhost:11434/api/tags
200 OK` (so Ollama is reachable + has models) — but the orchestrator
console shows no models.

Cause: the control plane is running with
`BOB_REQUIRE_PROVIDER_APPROVAL=true`, so auto-discovered providers
land as `pending_approval=True, is_active=False` and the dispatcher
refuses to route to them.

Fix (one of):

1. Open the orchestrator console — pending providers render
   grayed-out with an inline **Approve** button. Click it.
2. Approve via the API:
   ```bash
   curl -X POST -H 'Authorization: Bearer <admin-token>' \
     https://<control-plane>/api/v1/orchestrator/providers/<id>/approve
   ```
3. If you want auto-approval as the default (the standard behavior
   since 0.12.1), unset `BOB_REQUIRE_PROVIDER_APPROVAL` (or set it
   to `false`) in the control-plane env and restart `bob-api`.

See [CONFIGURATION.md](CONFIGURATION.md#provider-auto-discovery-since-0121)
for the security trade-off behind the env var.

## Related Documents

- [GPU_SERVICES.md](GPU_SERVICES.md) — GPU pipeline services
- [ARCHITECTURE.md](ARCHITECTURE.md) — System architecture overview
- [CONFIGURATION.md](CONFIGURATION.md) — All environment variables
- [INSTALL_PROD.md](INSTALL_PROD.md) — Production deployment guide
