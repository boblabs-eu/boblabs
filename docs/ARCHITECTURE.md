# Bob Labs — System Architecture

## 1. System Overview

Bob Labs is a distributed AI operations platform consisting of:

- **Control Plane** — Centralized management, orchestration, API, database, UI
- **Agents** — Lightweight services on GPU servers for metrics, commands, and script execution
- **GPU Services** — Standalone FastAPI microservices for media generation (audio, video, TTS, STT)
- **Sandbox** — Isolated container for executing untrusted code from lab agents
- **Remotion API** — React-to-MP4 video rendering service

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CONTROL PLANE                                │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ React UI │  │ FastAPI  │  │ Workflow  │  │  PostgreSQL 16   │  │
│  │ :3000    │  │ :8000    │  │  Engine   │  │  :5432           │  │
│  └────┬─────┘  └────┬─────┘  └─────┬─────┘  └──────────────────┘  │
│       │              │              │                                │
│       │         ┌────┴──────────────┴─────┐   ┌────────────────┐   │
│       └────────►│   WebSocket Hub         │   │   Qdrant       │   │
│                 │   (FastAPI built-in)    │   │   (vector DB)  │   │
│                 └────────┬───────────────┘   │   :6333         │   │
│                          │                    └────────────────┘   │
│                              ┌───────────┐  ┌───────────────┐   │
│                              │ Sandbox   │  │ Remotion API  │   │
│                              │ (per-lab) │  │ :3020         │   │
│                              └───────────┘  └───────────────┘   │
│                                                                     │
└─────────────────┬───────────────────────────────────────────────────┘
                  │  WebSocket + HTTP
                  │
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
┌────────────┐ ┌────────────┐ ┌────────────┐
│ Agent 1    │ │ Agent 2    │ │ Agent N    │
│ :9100      │ │ :9100      │ │ :9100      │
│ :9101      │ │ :9101      │ │ :9101      │
│            │ │            │ │            │
│ GPU Svcs:  │ │ GPU Svcs:  │ │ GPU Svcs:  │
│ :3014-3019 │ │ :3014-3019 │ │ :3014-3019 │
│ LLM       *│ │ LLM       *│ │ LLM       *│
└────────────┘ └────────────┘ └────────────┘

* LLM providers are pluggable through the dispatcher. Bob-api supports Ollama
  (default :11434), vLLM/HuggingFace (default :8000), OpenAI, Anthropic,
  xAI/Grok, Groq, and DeepSeek out of the box. See
  [DISPATCHER_AND_MODEL_ROUTING.md](DISPATCHER_AND_MODEL_ROUTING.md) for the
  full list and selection logic.
```

## 2. Component Architecture

### 2.1 Control Plane

The FastAPI backend is the central orchestration hub.

```
control-plane/
├── app/
│   ├── main.py                     # FastAPI app, router registration, startup events
│   ├── config.py                   # Environment-based configuration (Settings class)
│   ├── database.py                 # Async SQLAlchemy engine + session factory
│   │
│   ├── api/
│   │   ├── dependencies.py         # JWT auth, DB session injection, get_current_user
│   │   └── routes/
│   │       ├── auth.py             # POST /auth/token
│   │       ├── servers.py          # Server CRUD, metrics, processes, services
│   │       ├── commands.py         # Remote command execution (single + batch)
│   │       ├── workflows.py        # Workflow CRUD + parallel execution
│   │       ├── projects.py         # Project CRUD + themes
│   │       ├── modules.py          # Modules → Steps → Tasks (under projects)
│   │       ├── resources.py        # Shared resources + project linking
│   │       ├── orchestrator.py     # AI providers, models, agents, conversations, settings
│   │       ├── labs.py             # Lab CRUD + lifecycle + agents + tools + messages
│   │       ├── rag.py              # RAG collections, documents, search, access control
│   │       ├── tool_sets.py        # Reusable tool collections
│   │       ├── prompt_templates.py # Prompt template CRUD
│   │       ├── library_agents.py   # Standalone agent definitions
│   │       ├── cron_jobs.py        # CRON job library
│   │       ├── tool_configs.py     # Tool-specific configs (SMTP, Twitter API keys)
│   │       ├── web3.py             # Crypto prices, wallets, portfolio
│   │       ├── metrics.py          # Cached agent metrics
│   │       ├── news.py             # RSS feed aggregation
│   │       ├── access_tokens.py    # Admin token management + trial requests
│   │       └── public.py           # Unauthenticated: trial submit, blog, token validate
│   │
│   ├── websocket/
│   │   ├── hub.py                  # ConnectionManager singleton (agents + clients)
│   │   ├── agent_handler.py        # Agent WS handler (auth, metrics, commands)
│   │   └── client_handler.py       # UI client WS handler (subscriptions, broadcasts)
│   │
│   ├── services/
│   │   ├── lab_runner.py           # Lab execution engine (loop strategies, tool calls)
│   │   ├── lab_dispatcher.py       # LLM dispatch for labs (load-balanced)
│   │   ├── lab_scheduler.py        # CRON-based lab scheduling
│   │   ├── llm_provider.py         # LLM provider abstraction (Ollama, HF, OpenAI, Anthropic)
│   │   ├── tool_executor.py        # 40 built-in tools + execution engine
│   │   ├── conversation_service.py # Multi-turn chat, streaming
│   │   ├── orchestrator_service.py # AI orchestration engine
│   │   ├── rag_service.py          # RAG collection/document management
│   │   ├── rag_ingest.py           # Document extraction + chunking
│   │   ├── embedding_service.py    # Text → vector embeddings (sentence-transformers)
│   │   ├── lightrag_service.py     # LightRAG graph-enhanced retrieval
│   │   ├── authorization.py        # ACL permission checks
│   │   ├── email_service.py        # SMTP email notifications
│   │   ├── container_manager.py    # Docker sandbox lifecycle
│   │   ├── server_service.py       # Server registry + live status
│   │   ├── command_service.py      # Remote command execution
│   │   ├── workflow_service.py     # Workflow orchestration
│   │   ├── project_service.py      # Project management
│   │   ├── module_service.py       # Module/step/task management
│   │   ├── resource_service.py     # Resource management
│   │   ├── web3_service.py         # Crypto wallet + portfolio tracking
│   │   ├── metrics_service.py      # Metrics caching
│   │   ├── news_service.py         # RSS feed fetching
│   │   └── pipelines/              # Media pipeline registry
│   │       ├── base.py             # MediaPipeline ABC
│   │       ├── riffusion.py        # Riffusion pipeline
│   │       ├── musicgen.py         # MusicGen pipeline
│   │       ├── bark.py             # Bark TTS pipeline
│   │       ├── rvc.py              # RVC voice conversion pipeline
│   │       ├── coqui_tts.py        # CoquiTTS pipeline
│   │       ├── stt.py              # STT (Whisper) pipeline
│   │       ├── ltx_video.py        # LTX-Video pipeline
│   │       └── wan_video.py        # Wan-Video pipeline
│   │
│   ├── engine/
│   │   ├── executor.py             # Workflow step executor
│   │   ├── scheduler.py            # Parallel workflow scheduling
│   │   └── parser.py               # YAML/JSON workflow parser
│   │
│   ├── models/                     # SQLAlchemy 2.0 ORM (Mapped[] + mapped_column)
│   │   ├── base.py                 # Declarative base
│   │   ├── server.py               # Server, CommandHistory
│   │   ├── project.py              # Project, ProjectModule, ModuleStep, ModuleTask
│   │   ├── workflow.py             # Workflow, WorkflowStep
│   │   ├── execution.py            # WorkflowExecution, ExecutionLog
│   │   ├── resource.py             # Resource, ResourceProject
│   │   ├── orchestrator.py         # AIProvider, AIModel, AIAgent, Lab, LabAgent,
│   │   │                           # LabMessage, LabMemory, LabResource, LabScheduleLog,
│   │   │                           # OrchestratorSettings, Conversation, Message,
│   │   │                           # ToolSet, PromptTemplate, LibraryAgent, CronJob
│   │   ├── rag.py                  # RagCollection, RagDocument, LabRagAccess
│   │   ├── web3.py                 # Web3Settings, Wallet, PortfolioSnapshot
│   │   ├── access_token.py         # AccessToken, TrialRequest, QuoteRequest
│   │   └── blog.py                 # BlogPost, BlogToken, ThemeColor
│   │
│   ├── schemas/                    # Pydantic v2 (Create/Update/Response variants)
│   │   ├── server.py
│   │   ├── project.py
│   │   ├── workflow.py
│   │   ├── command.py
│   │   ├── module.py
│   │   ├── resource.py
│   │   ├── orchestrator.py         # AI + Lab schemas
│   │   └── rag.py
│   │
│   ├── repositories/               # Async data access layer (flush, not commit)
│   │   ├── server_repo.py
│   │   ├── project_repo.py
│   │   ├── workflow_repo.py
│   │   ├── execution_repo.py
│   │   ├── module_repo.py
│   │   ├── resource_repo.py
│   │   ├── orchestrator_repo.py
│   │   ├── lab_repo.py
│   │   ├── rag_repo.py
│   │   ├── access_token_repo.py
│   │   └── blog_post_repo.py
│   │
│   └── migrations/                 # Single consolidated bootstrap
│       └── init.sql                # Full schema (run once on empty pgdata; see git history for incremental change context)
```

### 2.2 Agent

Runs on each GPU server. Connects to the control plane via WebSocket.

```
agent/
├── app/
│   ├── main.py                 # Entry point, WS connection loop
│   ├── config.py               # Agent name, control plane URL, service URLs
│   │
│   ├── collectors/             # Metrics collectors (periodic push)
│   │   ├── cpu.py              # CPU usage, temperature, load average
│   │   ├── gpu.py              # GPU utilization, VRAM, temperature (nvidia-smi)
│   │   ├── memory.py           # RAM usage
│   │   ├── network.py          # Network bandwidth (bytes in/out)
│   │   ├── disk.py             # Disk usage per mount
│   │   └── system.py           # OS info, kernel, uptime
│   │
│   ├── inspectors/             # On-demand system inspection
│   │   ├── processes.py        # Top processes by CPU/memory
│   │   ├── services.py         # systemctl service status
│   │   ├── crontab.py          # Cron job listing
│   │   ├── ports.py            # Open ports (ss/netstat)
│   │   └── firewall.py         # UFW firewall rules
│   │
│   ├── executor/               # Remote command execution
│   │   └── runner.py           # Subprocess runner with streaming output
│   │
│   ├── metrics/                # Prometheus metrics exposition
│   │   └── exporter.py         # /metrics endpoint (:9100)
│   │
│   └── websocket/              # WebSocket client
│       └── client.py           # Auto-reconnect, heartbeat, metrics push
```

### 2.3 Sandbox

Isolated FastAPI container for executing untrusted code from lab agents.

- `POST /python_exec` — Execute Python code in a lab-scoped workspace
- `POST /shell_exec` — Execute whitelisted shell commands (curl, ffmpeg, yt-dlp, etc.)
- No access to API, database, or secrets
- Resource limits: 2 GB memory, 2 CPUs
- Output truncation and timeout enforcement

### 2.4 Remotion API

Node.js service that renders React/TSX components to MP4 video.

- `POST /render` — Accept React component code + render params, return base64 MP4
- Uses `@remotion/bundler` + `@remotion/renderer`
- 4 GB memory limit, 2 CPUs
- Port 3020 (internal only)

### 2.5 Script Runner

FastAPI service on GPU servers for executing GPU-accelerated scripts.

- Auto-discovers scripts in `/opt/bob-scripts/` via `BOB_SCRIPT_META` docstring convention
- Each script exposes `run(args, output_dir) → dict`
- Supports isolated venv/conda environments per script
- Port 9101

### 2.6 GPU Services

Standalone FastAPI microservices for media generation. See [GPU_SERVICES.md](GPU_SERVICES.md).

| Service | Port | Model | Purpose |
|---------|------|-------|---------|
| musicgen-api | 3014 | Meta AudioCraft MusicGen | Text-to-music |
| bark-api | 3015 | Suno Bark | TTS + singing |
| rvc-api | 3016 | RVC | Voice conversion |
| coqui-tts-api | 3017 | CoquiTTS XTTS v2 | TTS + voice cloning |
| stt-api | 7865 | OpenAI Whisper | Speech-to-text |
| ltx-video-api | 3018 | LTX-2.3 22B DiT | Text/image → video |
| wan-video-api | 3019 | Wan 2.2 5B | Text/image → video |

All services auto-unload models after configurable idle timeout to free VRAM.

## 3. Communication Protocol

### 3.1 WebSocket Messages

All messages use JSON with this envelope:

```json
{
  "type": "message_type",
  "id": "uuid",
  "timestamp": "ISO8601",
  "payload": { }
}
```

#### Agent → Control Plane

| Type | Description |
|------|-------------|
| `agent.register` | Agent announces itself with system info |
| `agent.heartbeat` | Periodic health check (30s interval) |
| `agent.metrics` | Metrics snapshot (10s interval) |
| `agent.command.output` | Streaming command stdout/stderr |
| `agent.command.complete` | Command execution finished |
| `agent.inspection.result` | Process/service/crontab data |

#### Control Plane → Agent

| Type | Description |
|------|-------------|
| `command.execute` | Execute a command |
| `command.cancel` | Cancel running command |
| `inspection.request` | Request system inspection data |
| `workflow.step.execute` | Execute a workflow step |

#### Control Plane → UI Clients

| Type | Description |
|------|-------------|
| `lab.message` | Lab iteration message (agent/orchestrator output) |
| `lab.status` | Lab status change (running, paused, completed, failed) |
| `lab.file` | File created/modified in lab workspace |
| `server.status` | Server online/offline status change |
| `server.metrics` | Real-time metrics update |

### 3.2 REST API

The control plane exposes 100+ REST endpoints under `/api/v1/`. See [API_REFERENCE.md](API_REFERENCE.md) for the complete listing.

**Key endpoint groups:**

| Prefix | Purpose |
|--------|---------|
| `/auth` | JWT token exchange |
| `/servers` | Server CRUD, metrics, inspection |
| `/commands` | Remote command execution |
| `/workflows` | Workflow CRUD + execution |
| `/projects` | Project management + themes |
| `/projects/{id}/modules` | Modules, steps, tasks |
| `/resources` | Shared resources |
| `/orchestrator` | AI providers, models, agents, conversations, settings, pipelines |
| `/labs` | Lab CRUD + lifecycle + agents + tools + messages + memory |
| `/rag` | Collections, documents, search, access control |
| `/tool-sets` | Reusable tool collections |
| `/prompt-templates` | Prompt templates |
| `/library-agents` | Standalone agent definitions |
| `/cron-jobs` | CRON job library |
| `/tool-configs` | Tool-specific configurations |
| `/web3` | Crypto prices, wallets, portfolio |
| `/metrics` | Cached server metrics |
| `/news` | RSS feed aggregation |
| `/access-tokens` | Admin token management |
| `/public` | Unauthenticated endpoints (trial, blog, token validation) |

## 4. Database

### 4.1 Schema Overview

PostgreSQL 16 with 22 sequential migrations. Key table groups:

**Infrastructure:** `servers`, `command_history`, `workflows`, `workflow_steps`, `workflow_executions`, `execution_logs`

**Projects:** `projects`, `project_modules`, `module_steps`, `module_tasks`, `resources`, `resource_projects`, `theme_colors`

**AI & Orchestration:** `orchestrator_settings`, `ai_providers`, `ai_models`, `ai_agents`, `conversations`, `messages`, `tool_sets`, `prompt_templates`, `library_agents`, `cron_jobs`

**Labs:** `labs`, `lab_agents`, `lab_tools`, `lab_messages`, `lab_memories`, `lab_resources`, `lab_schedule_log`, `llm_events`

**RAG:** `rag_collections`, `rag_documents`, `lab_rag_access`

**Web3:** `web3_settings`, `wallets`, `portfolio_snapshots`

**Access Control:** `access_tokens`, `trial_requests`, `quote_requests`

**Content:** `blog_posts`, `blog_tokens`

### 4.2 Key Design Patterns

- **UUID primary keys** on all tables
- **JSONB columns** for flexible data: `tools`, `links`, `themes`, `acl`, `capabilities`, `parameters`, `breakdown`
- **ACL JSONB** on projects, resources, conversations, wallets for per-record access control
- **Singleton pattern** for `orchestrator_settings` and `web3_settings` (id=1)
- **Soft references** between labs and AI entities (model_id, provider references)

## 5. Security Model

- **Agent authentication** — Shared `AGENT_SECRET` token validated on WebSocket connection
- **API authentication** — JWT (HS256) with configurable expiry (default: 24h)
- **Token-based access** — Admin generates access tokens; users exchange tokens for JWTs
- **WebSocket auth** — JWT passed in initial connection handshake
- **Sandbox isolation** — Per-lab containers with no API/DB/secret access, resource limits, shell whitelist
- **RAG access control** — Collection access explicitly granted per lab
- **ACL enforcement** — JSONB ACL on projects, resources, conversations
- **CORS** — Configurable (defaults to allow all; restrict in production)
- **Network isolation** — `rag-internal` network restricts Qdrant access to API only

## 6. Deployment Model

### Docker Compose Services (Control Plane)

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| bob-db | PostgreSQL 16 | 5435:5432 | Database |
| bob-api | FastAPI | 8888:8000 | Control plane API |
| bob-ui | React + Nginx | 3000:80 | Frontend |
| bob-sandbox | FastAPI | — (internal) | Code execution |
| bob-remotion | Node.js | — (internal) | Video rendering |
| bob-qdrant | Qdrant | 6333:6333 | Vector store |

### Networks

| Network | Type | Purpose |
|---------|------|---------|
| `bob-network` | bridge | Main inter-service communication |
| `rag-internal` | bridge (internal) | API ↔ Qdrant only (security isolation) |

### Volumes

| Volume | Purpose |
|--------|---------|
| `pgdata` | PostgreSQL data |
| `lab_resources` | Shared lab workspaces (mounted in API + sandbox) |
| `qdrant_data` | Vector store persistence |
| `qdrant_staging` | RAG file staging |
| `lightrag_data` | LightRAG knowledge graphs |

### GPU Server (Agent + Services)

| Component | Deployment | Port |
|-----------|-----------|------|
| bob-agent | systemd | 9100 |
| bob-script-runner | systemd | 9101 |
| GPU services | Docker Compose or systemd | 3014–3019, 7865 |
| LLM provider | Ollama / vLLM | 11434 / 8000 |

## 7. AI Orchestrator & Lab System

### 7.1 LLM Provider Layer

The platform supports multiple LLM backends through a unified provider abstraction:

```
LLMProvider (ABC)
├── OllamaProvider          — Local Ollama instances
├── HuggingFaceProvider     — vLLM / TGI endpoints
├── OpenAICompatibleProvider — OpenAI, Grok/xAI, Groq, DeepSeek
└── AnthropicProvider       — Claude API
```

**Supported provider types:**

| Type | Backend | Auth |
|------|---------|------|
| `ollama` | Ollama API | None |
| `huggingface` | vLLM / TGI | Bearer token |
| `openai` | Any OpenAI-compatible | Bearer token |
| `anthropic` | Anthropic Claude | x-api-key |
| `openai_cloud` | OpenAI API | Bearer token |
| `xai` | xAI / Grok | Bearer token |
| `groq` | Groq | Bearer token |
| `deepseek` | DeepSeek | Bearer token |

### 7.2 Lab Tool System

Labs provide agents with 40 built-in tools (auto-discovered from `tool_*.py` modules). See [TOOLS_AND_SANDBOX.md](TOOLS_AND_SANDBOX.md) for the complete reference.

| Category | Tools |
|----------|-------|
| Reasoning | `think` |
| Memory | `memory_save`, `memory_search`, `handle_memory` |
| File I/O | `file_read`, `file_write` |
| Code Execution | `python_exec`, `shell_exec` |
| Web | `web_search`, `web_extract`, `browser_navigate`, `browser_snapshot` |
| Media | `image_generate`, `audio_generate`, `media_pipeline`, `audio_mix`, `video_generate` |
| RAG | `rag_list_collections`, `rag_search`, `rag_ingest` |
| Diagrams | `mermaid_to_img`, `excalidraw` |
| Communication | `call_agent`, `mail`, `twitter` |
| Data | `blockchain`, `youtube` |
| Utility | `clock` |

### 7.3 Script Runner (GPU Model Execution)

Heavy GPU models run on GPU servers via the Script Runner, keeping them separate from the sandboxed lab environment.

```
GPU Server                          Control Plane
┌─────────────────────┐            ┌──────────────────────┐
│  bob-script-runner   │  HTTP     │  tool_executor.py     │
│  FastAPI :9101       │◄──────────│  audio_generate tool  │
│                      │           │                       │
│  /opt/bob-scripts/   │  base64   │  Saves to workspace/  │
│  ├── riffusion.py    │──────────►│  output/generated_*   │
│  ├── stable_audio.py │  files    │                       │
│  └── musicgen.py     │           │                       │
└─────────────────────┘            └──────────────────────┘
```

### 7.4 Media Pipeline Tool

The `media_pipeline` tool provides a modular interface for media generation via registered pipeline backends. Unlike `audio_generate` (Script Runner), pipelines communicate directly with dedicated HTTP APIs.

**Pipeline Registry:**

| Pipeline | Backend | Media Type |
|----------|---------|------------|
| `riffusion` | Riffusion API | Audio |
| `musicgen` | MusicGen API | Audio |
| `bark` | Bark API | Audio |
| `rvc` | RVC API | Audio |
| `coqui_tts` | CoquiTTS API | Audio |
| `stt` | Whisper API | Text (transcription) |
| `ltx_video` | LTX-Video API | Video |
| `wan_video` | Wan-Video API | Video |

**Adding a new pipeline:**

1. Create `control-plane/app/services/pipelines/my_pipeline.py` extending `MediaPipeline`
2. Register in `PIPELINE_REGISTRY` in `pipelines/__init__.py`
3. Add an `AIProvider` with `provider_type = "my_pipeline"` in the UI
4. Select `media_pipeline:my_pipeline` in lab/agent tool config

## 8. Frontend

React 18 SPA with dark theme, WebSocket live updates, and 20+ pages:

| Page | Purpose |
|------|---------|
| Dashboard | System overview with server status grid |
| Servers | GPU server details, metrics, processes, services |
| Commands | Remote command execution (single + batch) |
| Workflows | YAML workflow management and execution |
| Orchestrator | AI provider/model/agent configuration + conversations |
| Labs | Multi-agent lab creation, execution, monitoring |
| RAG | Collection management, document ingestion, search |
| Projects | Project organization with modules/steps/tasks |
| Resources | Shared resource management |
| Web3 | Wallet tracking, portfolio, price feeds |
| Terminal | Web-based terminal access to servers |
| News | RSS feed reader |
| Admin | Access token management, trial requests, blog |
| Blog | Published blog posts |
| Live | Real-time lab/server monitoring (public) |
| Docs | Built-in documentation viewer |
| Landing | Public marketing pages (EN/FR) |

**State management:** React Context for auth, per-page local state. WebSocket service for real-time updates with auto-reconnect.

## 9. Startup Events

The control plane runs these tasks on startup:

1. **Portfolio snapshot scheduler** — Periodic Web3 portfolio recording
2. **Lab cron scheduler** — Schedule lab executions based on cron expressions
3. **Legacy provider renaming** — Normalize provider display names
4. **Stuck labs reset** — Reset labs stuck in "running" state (crash recovery)
5. **Orphaned provider linking** — Link AI providers to servers by matching base_url host
