# Bob Labs — Configuration Reference

All environment variables across all services.

---

## Control Plane (`control-plane/app/config.py`)

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://bobmanager:changeme_in_production@bob-db:5432/bobmanager` | PostgreSQL connection string |

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_SECRET` | `change-this-to-a-random-secret-token` | Shared secret for agent WebSocket authentication. Must match agent config. |
| `JWT_SECRET` | `change-this-jwt-secret-key` | Secret key for JWT token signing |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_EXPIRE_MINUTES` | `1440` | JWT expiry (default: 24 hours) |

### Server

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Bind address for the FastAPI server |
| `PORT` | `8000` | Listen port |

### Admin

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_SECRET` | `""` | Password for `/admin` panel access |
| `ADMIN_EMAIL` | `""` | Email address for trial request notifications |
| `APP_BASE_URL` | `http://localhost:3000` | Public URL of the platform (used in emails) |

### Email / SMTP

| Variable | Default | Description |
|----------|---------|-------------|
| `SMTP_HOST` | `""` | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | `""` | SMTP username |
| `SMTP_PASSWORD` | `""` | SMTP password |
| `SMTP_FROM` | `""` | Sender email address |
| `SMTP_TLS` | `true` | Use STARTTLS |

### RAG / Embeddings

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_URL` | `http://bob-qdrant:6333` | Qdrant vector DB endpoint |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model for embeddings |
| `EMBEDDING_BATCH_SIZE` | `64` | Batch size for embedding generation |
| `RAG_DEFAULT_CHUNK_SIZE` | `512` | Default chunk size (tokens) for document splitting |
| `RAG_DEFAULT_CHUNK_OVERLAP` | `64` | Default chunk overlap (tokens) |
| `RAG_DEFAULT_SPLITTER` | `recursive` | Default text splitter (recursive, sentence, paragraph, fixed) |
| `RAG_MAX_RESULTS` | `20` | Maximum results per RAG query |
| `RAG_STAGING_PATH` | `/data/rag_staging` | Temporary staging directory for file uploads |
| `LIGHTRAG_STORAGE_PATH` | `/data/lightrag` | Storage directory for LightRAG graph data |

---

## Agent (`agent/app/config.py`)

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_NAME` | `gpu-server` | Display name for this agent in the control plane |
| `CONTROL_PLANE_URL` | `ws://localhost:8000/ws/agent` | WebSocket URL(s) to connect to. **Comma-separated** for multi-plane support. |
| `AGENT_SECRET` | `change-this-to-a-random-secret-token` | Must match control plane's `AGENT_SECRET` |

### Metrics & Heartbeat

| Variable | Default | Description |
|----------|---------|-------------|
| `METRICS_PORT` | `9100` | Prometheus metrics endpoint port |
| `HEARTBEAT_INTERVAL` | `30` | Seconds between heartbeat messages |
| `METRICS_INTERVAL` | `10` | Seconds between metrics collection |

### Service URLs

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRIPT_RUNNER_URL` | `http://localhost:9101` | Script runner service endpoint |
| `RIFFUSION_URL` | `http://localhost:3013` | Riffusion music generation |
| `MUSICGEN_URL` | `http://localhost:3014` | MusicGen instrumental generation |
| `BARK_URL` | `http://localhost:3015` | Bark speech/singing generation |
| `RVC_URL` | `http://localhost:3016` | RVC voice conversion |
| `COQUI_TTS_URL` | `http://localhost:3017` | CoquiTTS / XTTS v2 text-to-speech |
| `STT_URL` | `http://localhost:7865` | Speech-to-text (Whisper) |
| `LTX_VIDEO_URL` | `http://localhost:3018` | LTX-Video generation |
| `WAN_VIDEO_URL` | `http://localhost:3019` | Wan-Video generation |

---

## Docker Compose (`docker-compose.yml`)

### Ports

| Service | Internal Port | Default Bind | Purpose |
|---------|---------------|-------------|---------|
| `bob-db` | 5432 | `${BIND_ADDR:-0.0.0.0}:5435` | PostgreSQL |
| `bob-api` | 8000 | `0.0.0.0:8888` | Control plane API + WebSocket |
| `bob-ui` | 80 | `${BIND_ADDR:-0.0.0.0}:3000` | Frontend (Nginx + React) |
| `bob-qdrant` | 6333 | `${BIND_ADDR:-0.0.0.0}:6333` | Qdrant vector DB |

### Volumes

| Volume | Mount Point | Purpose |
|--------|-------------|---------|
| `bob_db_data` | `/var/lib/postgresql/data` | PostgreSQL data persistence |
| `bob_qdrant_data` | `/qdrant/storage` | Qdrant vector storage |
| `bob_lab_workspaces` | `/data/lab_workspaces` | Lab file storage |
| `bob_rag_staging` | `/data/rag_staging` | RAG file upload staging |
| `bob_lightrag_data` | `/data/lightrag` | LightRAG graph storage |
| `/var/run/docker.sock` | `/var/run/docker.sock` | Docker socket for sandbox management |

### Networks

| Network | Type | Purpose |
|---------|------|---------|
| `bob-network` | bridge | All services communicate |
| `rag-internal` | bridge (internal) | Qdrant ↔ bob-api only (no external access) |

### Key Environment Variables

| Variable | Used By | Description |
|----------|---------|-------------|
| `BIND_ADDR` | docker-compose | Bind host for ports. Set to `127.0.0.1` in production. |
| `POSTGRES_USER` | bob-db | Database username |
| `POSTGRES_PASSWORD` | bob-db | Database password |
| `POSTGRES_DB` | bob-db | Database name |

---

## GPU Services (`gpu-services/docker-compose.yml`)

Each GPU service accepts configuration via environment variables:

| Variable | Services | Description |
|----------|----------|-------------|
| `HF_TOKEN` | musicgen, bark, rvc | HuggingFace token for model downloads |
| `MODEL_NAME` | musicgen | Model variant (e.g., `facebook/musicgen-medium`) |
| `IDLE_TIMEOUT` | all GPU services | Seconds before unloading model from VRAM |

---

## Frontend (`frontend/.env`)

| Variable | Description |
|----------|-------------|
| `REACT_APP_CONTACT_EMAIL` | Contact email shown on landing page |

> **Note:** React environment variables are baked into the build at `docker compose build` time. Changes require a rebuild.

---

## Production Essentials

Generate strong secrets for production:

```bash
echo "POSTGRES_PASSWORD=$(openssl rand -base64 32)"
echo "AGENT_SECRET=$(openssl rand -hex 32)"
echo "JWT_SECRET=$(openssl rand -hex 32)"
echo "ADMIN_SECRET=$(openssl rand -hex 32)"
```

See [INSTALL_PROD.md](INSTALL_PROD.md) for the full production deployment guide.
