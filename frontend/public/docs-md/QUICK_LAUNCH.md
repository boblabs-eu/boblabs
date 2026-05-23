# Quick Launch

Get Bob Labs running on your own infrastructure in minutes. This guide covers the **control plane** (web UI, database, orchestrator) and one or more **GPU servers** (model providers, hardware monitoring agents).

The default deployment model is **self-hosted with Docker Compose** — no Kubernetes, no SaaS, no waiting list.

---

## 1. Requirements

### Control plane host

| Requirement | Minimum | Recommended |
|---|---|---|
| OS | Linux (Ubuntu 22.04+, Debian 12+) | Ubuntu 24.04 |
| CPU | 4 cores | 8+ cores |
| RAM | 8 GB | 16+ GB |
| Disk | 30 GB SSD | 100+ GB SSD |
| Network | reachable on chosen ports | private VLAN / VPN |

Required software:

- **Docker** ≥ 24.x
- **Docker Compose** v2 (bundled with recent Docker)
- **git**

> The control plane does not need a GPU. It is the brain — orchestrators, agents, RAG, scheduling, web UI and database all live here.

### GPU server host(s)

You may add as many GPU servers as you want. Each one auto-discovers and registers with the control plane.

| Requirement | Minimum | Recommended |
|---|---|---|
| OS | Linux with NVIDIA drivers | Ubuntu 24.04 + CUDA 12.x |
| GPU | 1× consumer GPU (8 GB VRAM) | 1+ × A100 / H100 / RTX 4090 |
| RAM | 16 GB | 64+ GB |
| Disk | 100 GB SSD | 1 TB+ NVMe (for models) |

Required software on each GPU server:

- **NVIDIA driver** matching your CUDA version
- **Docker** ≥ 24.x with the **NVIDIA Container Toolkit** (`nvidia-ctk`)
- **git**

Verify GPU access from Docker:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

If `nvidia-smi` prints your GPU(s), you're ready.

---

## 2. Deploy the control plane

On the host you want to run the platform from:

```bash
# 1. Clone
git clone https://github.com/bob-labs/bob-manager.git
cd bob-manager

# 2. Configure (copy the example file and adapt secrets)
cp .env.example .env
$EDITOR .env

# 3. Start
docker compose up -d
```

That's it. The web UI is now reachable at `http://<your-host>:3000`.

### What you should change in `.env`

At minimum, rotate the secrets:

| Variable | What it is |
|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL password (used internally by the stack) |
| `JWT_SECRET` | Signing key for user auth tokens |
| `AGENT_SECRET` | Shared token used by GPU-server agents to authenticate to the control plane |
| `ADMIN_SECRET` | Initial admin bootstrap secret |
| `ADMIN_EMAIL` | Email address of the first admin user |

Optional but useful:

- `REACT_APP_API_URL` / `REACT_APP_WS_URL` — public URL of the control plane if you put it behind a reverse proxy.
- `SMTP_*` — outgoing mail (account invitations, quote requests).
- `HF_TOKEN` — Hugging Face token for gated model downloads.

### Verify

```bash
docker compose ps           # all services should be "healthy"
docker compose logs -f bob-api   # follow control-plane logs
```

Open the UI, log in with `ADMIN_EMAIL` (use the password-reset / first-login flow), and you're in.

### Update later

```bash
git pull
docker compose pull
docker compose up -d
```

---

## 3. Deploy a GPU server

You can repeat this section on as many machines as you have GPUs.

### Option A — One-shot installer (recommended)

On the GPU host:

```bash
# 1. Clone the repo (only the agent + gpu-services folders are needed)
git clone https://github.com/bob-labs/bob-manager.git
cd bob-manager

# 2. Tell the host where the control plane lives
export CONTROL_PLANE_URL=http://<control-plane-host>:8000
export AGENT_SECRET=<the same value as on the control plane>

# 3. Install + start the host-level agent
sudo ./agent/install.sh

# 4. (Optional) start one or more GPU model providers
cd gpu-services
./install.sh
```

The **agent** runs as a systemd service (`bob-agent`). It performs hardware discovery, reports GPU/CPU/RAM telemetry to the control plane, and executes commands on behalf of the orchestrator (within its allow-list).

The **gpu-services** stack starts model providers (Ollama, vLLM, ComfyUI for image/video, TTS, etc.). Pick the modules you need from the menu — anything you don't enable simply stays off.

### Option B — Manual (Docker Compose only)

If you prefer to skip the host agent and just expose model endpoints:

```bash
cd gpu-services
docker compose up -d ollama        # Ollama provider
# or
docker compose -f ../docker-compose.qwen72b.yml up -d   # standalone vLLM model
```

Then add the provider in the UI under **Settings → Providers → Add provider**, pointing at `http://<gpu-host>:<port>`.

### Verify discovery

In the web UI, open **Hardware → Servers**. Within ~30 seconds you should see your GPU host appear with live GPU utilization, VRAM and temperature.

In **Models → Feed**, every running model on every host shows up with current load. The dispatcher will start routing requests to it automatically.

---

## What's next?

- [General Overview](?doc=GENERAL_OVERVIEW) — the 10-minute mental model
- [Architecture](?doc=ARCHITECTURE) — how the pieces fit together
- [Configuration](?doc=CONFIGURATION) — every `.env` flag explained
- [Labs](?doc=LABS) — build your first multi-agent workspace
- [Dispatcher & Model Routing](?doc=DISPATCHER_AND_MODEL_ROUTING) — how requests reach GPUs
- [Production Install](?doc=INSTALL_PROD) — TLS, reverse proxy, backups, hardening
