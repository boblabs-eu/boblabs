# Bob Labs — Orchestrator Architecture

## Overview

The AI Orchestrator is the multi-agent LLM orchestration engine at the core of Bob Labs. It provides:

- A **conversation interface** for direct interaction with LLMs (ChatGPT-style)
- A **lab execution engine** for persistent multi-agent workflows (see [LABS.md](LABS.md))
- **Multi-provider model routing** with load balancing (see [DISPATCHER_AND_MODEL_ROUTING.md](DISPATCHER_AND_MODEL_ROUTING.md))

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React)                          │
│  ┌─────────────┐  ┌──────────────────────┐  ┌────────────────┐  │
│  │ Conversation │  │    Chat Interface     │  │ Activity Feed  │  │
│  │  List Panel  │  │  (streaming tokens)   │  │ (real-time WS) │  │
│  └─────────────┘  └──────────────────────┘  └────────────────┘  │
└───────────────────────────┬──────────────────────────────────────┘
                            │ REST + SSE + WebSocket
┌───────────────────────────┴──────────────────────────────────────┐
│                    CONTROL PLANE (FastAPI)                        │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                 API Routes (/api/v1/orchestrator)           │  │
│  │  Settings · Providers · Models · Agents · Conversations    │  │
│  │  Messages · Pipelines                                      │  │
│  └──────────────────────────┬─────────────────────────────────┘  │
│                              │                                    │
│  ┌──────────────────────────┴─────────────────────────────────┐  │
│  │                      Service Layer                          │  │
│  │  ConversationService · OrchestratorService                  │  │
│  │  LabRunner · LabDispatcher · LLMProviderManager             │  │
│  └──────────┬───────────────┬─────────────────────────────────┘  │
│             │               │                                     │
│  ┌──────────┴──┐  ┌────────┴────────┐                            │
│  │ LLM Provider│  │  Lab Execution  │                            │
│  │ Abstraction │  │  Engine         │                            │
│  │             │  │                 │                            │
│  │ • Ollama    │  │ • Loop strategy │                            │
│  │ • HuggingFa │  │ • Tool executor │                            │
│  │ • OpenAI    │  │ • Memory mgmt  │                            │
│  │ • Anthropic │  │ • Scheduling   │                            │
│  │ • xAI/Groq  │  │                 │                            │
│  │ • DeepSeek  │  │                 │                            │
│  └──────┬──────┘  └─────────────────┘                            │
│         │                                                         │
│  ┌──────┴──────────────────────────────────────────────────────┐ │
│  │                    WebSocket Hub                              │ │
│  │  Agent ←→ Control Plane ←→ Frontend                          │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

## Core Concepts

### AI Providers

Connections to LLM backends. Each provider has a type, base URL, optional API key, and optional server association.

**Supported types:** `ollama`, `huggingface`, `openai`, `anthropic`, `openai_cloud`, `xai`, `groq`, `deepseek`

Providers can also represent GPU media services (e.g., `provider_type = "musicgen"` for the MusicGen pipeline). The dispatcher discovers providers by type and routes requests accordingly.

### AI Models

Models are registered under providers. Each model has:
- `model_identifier` — The actual model name (e.g., `qwen2.5:72b`)
- `capabilities` (JSONB) — Feature flags (text, vision, code, etc.)
- `parameters` (JSONB) — Default inference parameters
- `is_available` — Availability flag

### AI Agents

Pre-configured LLM roles. Each agent = model + system prompt + temperature + max tokens + tools.

Agents defined in the **Agents tab** (stored in `ai_agents`) are reusable across:
- **Conversations** — Assign an agent to a conversation to use its system prompt, model, and tools.
- **Labs** — Import agents from the global list into a lab. Lab agents can also be saved back to the global Agents list.

### Conversations

Multi-turn chat threads. Each conversation:
- Uses the default orchestrator model set in Orchestrator Settings
- Supports per-message model override (user can pick a different model for a single message)
- Supports optional **agent assignment** (`agent_id`) — the agent's system prompt and config are applied
- Supports optional **tool selection** (`tools` list) — enables tool calling in chat (same tools available in Labs)
- Supports SSE streaming for real-time token delivery
- Stores full message history with role, content, and tool calls
- Has ACL for access control (owner, editors, viewers)

### Orchestrator Settings

Singleton configuration record:
- `orchestrator_model` / `orchestrator_provider` — Default model for orchestration
- `orchestrator_server_id` — Preferred GPU server
- `max_concurrent_tasks` — Concurrency limit

## Database Schema

| Table | Purpose |
|-------|---------|
| `orchestrator_settings` | Singleton config |
| `ai_providers` | LLM API connections |
| `ai_models` | Registered models per provider |
| `ai_agents` | Agent definitions (name + prompt + model) |
| `conversations` | Chat threads with ACL, optional agent and tools |
| `messages` | Messages within conversations |
| `tool_sets` | Reusable tool collections |
| `prompt_templates` | Reusable system prompt templates |
| `library_agents` | Standalone agent definitions for lab reuse |
| `cron_jobs` | Scheduled job definitions |

## Conversation Message Flow

### Direct Response (Streaming)

```
User → POST /orchestrator/conversations/{id}/messages
    → ConversationService.send_message()
    → LLMProvider.chat_stream(model, messages)
    → SSE stream tokens to frontend
    → Save assistant message to DB
    → Broadcast activity via WebSocket
```

### With Tool Calling

```
User → "What's the price of ETH?"
    → LLM responds with tool_call: blockchain(action="balance", ...)
    → ToolExecutor.execute("blockchain", args)
    → Tool result appended to messages
    → LLM re-called with result
    → Final response streamed to user
```

## API Endpoints

All under `/api/v1/orchestrator`:

### Settings
| Method | Path | Description |
|--------|------|-------------|
| GET | `/settings` | Get orchestrator configuration |
| PUT | `/settings` | Update orchestrator configuration |

### Providers
| Method | Path | Description |
|--------|------|-------------|
| GET | `/providers` | List all AI providers (with server_name) |
| POST | `/providers` | Create provider |
| PUT | `/providers/{id}` | Update provider |
| DELETE | `/providers/{id}` | Delete provider |
| POST | `/providers/{id}/test` | Test provider connection |
| POST | `/providers/{id}/discover` | Discover available models |

### Models
| Method | Path | Description |
|--------|------|-------------|
| GET | `/models` | List all models |
| POST | `/models` | Register model to provider |
| PUT | `/models/{id}` | Update model |
| DELETE | `/models/{id}` | Delete model |

### Agents
| Method | Path | Description |
|--------|------|-------------|
| GET | `/agents` | List agents |
| POST | `/agents` | Create agent |
| PUT | `/agents/{id}` | Update agent |
| DELETE | `/agents/{id}` | Delete agent |

### Conversations
| Method | Path | Description |
|--------|------|-------------|
| GET | `/conversations` | List conversations |
| POST | `/conversations` | Create conversation |
| PUT | `/conversations/{id}` | Update conversation |
| DELETE | `/conversations/{id}` | Delete conversation |
| GET | `/conversations/{id}/messages` | Get message history |
| POST | `/conversations/{id}/messages` | Send message (SSE streaming response) |

### Pipelines
| Method | Path | Description |
|--------|------|-------------|
| GET | `/pipelines` | List available media pipelines |

### Builtin Tools
| Method | Path | Description |
|--------|------|-------------|
| GET | `/builtin-tools` | List all registered builtin tools with descriptions and sub-tools |

## Recommended Models

| Role | Model | VRAM | Notes |
|------|-------|------|-------|
| Orchestrator | Qwen 2.5 72B | ~40 GB | Strong reasoning + instruction following |
| Code Agent | DeepSeek Coder V2 33B | ~20 GB | Strong coding capabilities |
| General Agent | Llama 3.1 70B | ~40 GB | Good all-around performance |
| Fast Agent | Qwen 2.5 7B | ~5 GB | Quick responses for simple tasks |
| Vision Agent | Llama 3.2 Vision | ~6 GB | Image understanding |

Any OpenAI-compatible, Anthropic, or cloud-hosted model also works via the corresponding provider type.
