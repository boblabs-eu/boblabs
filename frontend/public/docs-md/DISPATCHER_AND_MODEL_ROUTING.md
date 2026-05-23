# Bob Labs — Dispatcher & Model Routing

## Overview

The dispatcher separates workflow logic from LLM provider mechanics. Instead of hard-coding a single endpoint, the control plane discovers all providers that host a requested model and routes to the best candidate — with load balancing, affinity tracking, and automatic failover.

**Source files:**
- `control-plane/app/services/lab_dispatcher.py` — Load balancer and routing engine
- `control-plane/app/services/llm_provider.py` — Provider abstraction and implementations

## Supported Provider Types

| Type | Class | Concurrency | API Format | Notes |
|------|-------|-------------|------------|-------|
| `ollama` | `OllamaProvider` | 1 (serial) | `/api/chat` | Local GPU, native tool calling |
| `huggingface` | `HuggingFaceProvider` | 4 | `/v1/chat/completions` | vLLM/TGI compatible |
| `openai` | `OpenAICompatibleProvider` | 4 | `/v1/chat/completions` | vLLM, LM Studio, any OpenAI-compatible |
| `anthropic` | `AnthropicProvider` | 4 | `/v1/messages` | System as top-level param, `tool_use` blocks |
| `openai_cloud` | Cloud preset | 4 | OpenAI API | Pre-configured `base_url` |
| `xai` | Cloud preset | 4 | OpenAI-compatible | Grok models |
| `groq` | Cloud preset | 4 | OpenAI-compatible | Ultra-low latency |
| `deepseek` | Cloud preset | 4 | OpenAI-compatible | DeepSeek models |

Cloud presets (`openai_cloud`, `xai`, `groq`, `deepseek`) use `OpenAICompatibleProvider` with pre-configured base URLs.

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│  Lab Runner / Conversation Service                         │
│     call_orchestrator(lab, messages)                        │
│     call_agent(agent, messages)                             │
└───────────────────────┬────────────────────────────────────┘
                        │
┌───────────────────────▼────────────────────────────────────┐
│  LabDispatcher._call_with_loadbalance(model_id, messages)  │
│                                                             │
│  1. Find ALL providers hosting model_identifier             │
│  2. Sort by: affinity → uncontested → least queue depth     │
│  3. Acquire provider semaphore slot                         │
│  4. Stream LLM response                                    │
│  5. Failover to next provider on error                      │
│  6. Record affinity on success                              │
│  7. Log events (queue → dispatch → response/failed)         │
└───────────────────────┬────────────────────────────────────┘
                        │
┌───────────────────────▼────────────────────────────────────┐
│  _ProviderSlot (one per provider, global singleton)         │
│  ┌──────────────────┐ ┌──────────────────┐                 │
│  │ asyncio.Semaphore │ │ _waiters counter  │                │
│  │ (1 for Ollama,   │ │ (queue depth for  │                │
│  │  4 for others)    │ │  load balancing)  │                │
│  └──────────────────┘ └──────────────────┘                 │
└───────────────────────┬────────────────────────────────────┘
                        │
┌───────────────────────▼────────────────────────────────────┐
│  LLMProvider (abstract base)                                │
│  ├── OllamaProvider      → /api/chat (streaming)           │
│  ├── HuggingFaceProvider → /v1/chat/completions            │
│  ├── OpenAICompatible    → /v1/chat/completions            │
│  └── AnthropicProvider   → /v1/messages                    │
└────────────────────────────────────────────────────────────┘
```

## Routing Algorithm

### Step 1: Provider Discovery

```python
# Find all providers that host the requested model
providers = [
    (provider, model)
    for provider in active_providers
    for model in provider.models
    if model.model_identifier == requested_model
    and model.is_available
]
```

The lookup key is `model_identifier` (e.g., `qwen2.5:72b`, `gpt-4o`). A model can be registered under multiple providers.

### Step 2: Provider Sorting

Providers are sorted using a three-tier priority:

1. **Caller affinity** — If this `(lab_id, caller_name)` previously succeeded on a specific provider, that provider is preferred. This keeps KV caches warm across turns.
2. **Uncontested** — Providers not currently pinned by another caller's affinity are preferred over busy ones.
3. **Least queue depth** — Among equal-priority providers, the one with the fewest waiters is chosen.

### Step 3: Execution with Failover

```
For each provider in sorted order:
    1. Log "queue" event (request enters queue)
    2. Acquire semaphore (blocks if at capacity)
    3. Log "dispatch" event (request sent to provider)
    4. Call provider.chat_stream() or provider.chat()
    5. On success:
       - Log "response" event (tokens, duration)
       - Record affinity: _caller_affinity[(lab_id, caller)] = provider_id
       - Return result
    6. On failure:
       - Log "failed" event (error, attempt number)
       - Try next provider
    7. All providers exhausted → raise error
```

### Concurrency Model

Each provider gets a `_ProviderSlot` with an `asyncio.Semaphore`:

| Provider Type | Max Concurrent | Rationale |
|---------------|---------------|-----------|
| Ollama | 1 | Single-GPU sequential execution |
| All others | 4 | API servers handle concurrency |

Slots are **global singletons** — concurrency is shared across all Labs and conversations using the same provider. This prevents multiple callers from overcommitting a single GPU backend.

### Caller Affinity

```python
_caller_affinity: dict[tuple[UUID, str], UUID] = {}
# Maps (lab_id, caller_name) → provider_id
```

- When an orchestrator or agent call succeeds, the provider is recorded.
- On the next call, that provider is tried first.
- Benefit: GPU backends (especially Ollama) cache the model's KV state. Re-using the same provider avoids cold-start latency.
- Affinity is a preference, not a lock — if the preferred provider is busy, the dispatcher falls back to others.

## LLM Provider Interface

```python
class LLMProvider(ABC):
    async def chat_completion(
        self, model: str, messages: list[dict],
        temperature: float, max_tokens: int,
        tools: list[dict] | None = None
    ) -> AsyncGenerator[dict, None]:
        """Stream tokens as dicts with 'content' and optional 'tool_calls'."""

    async def chat(self, ...) -> dict:
        """Collect all streamed tokens into a single response dict."""

    async def list_models(self) -> list[dict]:
        """Discover available models from the provider."""

    async def health_check(self) -> bool:
        """Test provider connectivity."""
```

### Multimodal Support

Each provider converts messages to its native format:

| Provider | Image Format |
|----------|-------------|
| Ollama | `images: [base64_raw]` field |
| OpenAI / HF | `content: [{type: "image_url", image_url: {url: "data:image/png;base64,..."}}]` |
| Anthropic | `content: [{type: "image", source: {type: "base64", ...}}]` |

### Tool Calling

| Provider | Tool Format |
|----------|------------|
| Ollama | OpenAI-style `tools` array + `tool_calls` in response |
| OpenAI / HF | Native `tools` parameter, SSE delta accumulation |
| Anthropic | `tool_use` content blocks, converted to OpenAI format on return |

The dispatcher returns tool calls in a normalized OpenAI-compatible format regardless of the underlying provider.

## LLM Event Logging

Every LLM call produces a series of events sharing the same `request_id`:

| Event Type | When | Payload |
|------------|------|---------|
| `queue` | Request enters the dispatch queue | model, caller_type, caller_name |
| `dispatch` | Semaphore acquired, request sent | provider_name, server_name, attempt |
| `response` | Successful response received | tokens_in, tokens_out, duration_ms |
| `failed` | Provider returned an error | error message, attempt number |

Events are stored in the `llm_events` table and visible in the **LLM Activity** dashboard in the frontend.

### Caller Types

| `caller_type` | Context |
|----------------|---------|
| `lab_orchestrator` | Lab orchestrator LLM call |
| `lab_agent` | Lab agent LLM call |
| `conversation` | Direct conversation (chat) call |

## HTTP Configuration

```python
_TIMEOUT = httpx.Timeout(
    connect=15.0,   # Connection establishment
    read=600.0,     # Streaming read (10 minutes for long generations)
    write=15.0,     # Request send
    pool=30.0       # Connection pool wait
)
```

## Server Affinity

Providers can optionally be associated with a `server_id` (FK to the `servers` table). This links AI providers to physical GPU servers, enabling:
- The orchestrator settings `orchestrator_server_id` to prefer providers on a specific server
- The frontend to show which GPU server hosts each provider
- Infrastructure monitoring correlation

## Related Documents

- [ORCHESTRATOR.md](ORCHESTRATOR.md) — Orchestrator settings and conversation system
- [LABS.md](LABS.md) — Lab runtime and agent execution
- [ARCHITECTURE.md](ARCHITECTURE.md) — System architecture overview
- [GPU_SERVICES.md](GPU_SERVICES.md) — GPU pipeline services