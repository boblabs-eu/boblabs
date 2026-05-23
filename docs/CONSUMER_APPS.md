# Consumer Apps — Plugging a Private App into Bob-API

Bob-api exposes an internal HMAC-authenticated channel that lets a separately
deployed application drive labs, GPU workflows, LLMs, STT, and ffmpeg ops
without sharing a process or a database. Use it to build user-facing products
on top of bob-api's heavy lifting while keeping the two systems independently
deployable.

## Why a separate consumer app?

Run user-facing products that own their own data — accounts, billing, app-
specific tables — while reusing bob-api's heavy lifting:

- Lab orchestration (multi-agent, tools, sandboxes)
- LLM dispatcher with load balancing across providers
- ComfyUI workflow execution (Flux, LTX, etc.)
- STT, ffmpeg, video rendering

The consumer app stays small. Bob-api stays generic. The boundary is a few
HTTP endpoints behind a per-app HMAC secret.

## Registering an app

bob-ui → Admin → Consumer Apps → "Create app." Pick a slug (e.g. `myapp`),
the UI returns a freshly generated HMAC secret **once**. Copy it into the
consumer app's `.env`:

```env
BOB_API_URL=http://bob-api:8000
BOB_APP_ID=myapp
BOB_APP_SECRET=<hex64 from bob-ui>
```

Bob-api stores only the bcrypt hash. Revoke or rotate from the same admin UI.

## Authenticating a request

Every request signs the body with HMAC-SHA256:

```text
message  = "<unix_seconds>.<raw_body_bytes>"
signature = hex(hmac_sha256(BOB_APP_SECRET, message))
```

Headers on every call:

```http
Content-Type: application/json
X-App-Id:        <slug>
X-App-Timestamp: <unix_seconds>
X-App-Signature: <hex>
```

Bob-api rejects:

- missing or unknown `X-App-Id` → 401
- timestamp drift > **300 s** → 401 (replay protection)
- signature mismatch → 401
- revoked key → 401

A reference signer in Python:

```python
import hmac, hashlib, time, json, httpx

def call(path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    sig = hmac.new(
        BOB_APP_SECRET.encode(),
        ts.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    r = httpx.post(
        f"{BOB_API_URL}{path}",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-App-Id": BOB_APP_ID,
            "X-App-Timestamp": ts,
            "X-App-Signature": sig,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
```

## Endpoints

All paths live under `/api/v1/internal/apps/*`.

### Lab lifecycle

| Endpoint | Purpose |
|---|---|
| `POST /import_lab` | Idempotent import of a lab blueprint (JSON). Tags it `acl.tag=app:<app_id>:template:<name>` so it's hidden from the operator UI. Returns the lab id. See [Lab blueprint](#lab-blueprint). |
| `POST /run_lab` | Clone a template lab, seed `context_files`, run agents, copy named `output_artifacts` to the shared volume, post a callback. |

### Standalone agents

| Endpoint | Purpose |
|---|---|
| `POST /create_agent` | Create an app-owned standalone agent (library_agent). Idempotent on `(app_id, name)`. See [Agents](#agents). |
| `POST /import_agent` | Import an `AgentBlueprint` JSON (full config including `rag_access`). Idempotent unless `force_refresh=true`. |
| `POST /list_agents` | List agents owned by this app. |
| `POST /delete_agent` | Hard-delete an app-owned agent. Body: `{"name": "<short>"}`. |
| `POST /run_agent` | Invoke an agent once with a user message. Async + callback (like `/run_lab`). Spawns an ephemeral single-agent lab, runs it, returns the final assistant content via signed callback. |
| `POST /list_agent_runs` | List recent ephemeral-lab runs of an agent (both `/run_agent` triggers and cron firings). Use this to poll cron results since cron doesn't post callbacks. |

### RAG collections

| Endpoint | Purpose |
|---|---|
| `POST /create_rag` | Create an app-owned vector collection. Idempotent on `(app_id, name)`. See [RAG](#rag). |
| `POST /list_rags` | List all RAG collections owned by this app. |
| `POST /update_rag` | Update mutable collection metadata (`display_name`, `description`, `lightrag_search_mode`). Embedding model + distance metric are immutable. |
| `POST /delete_rag` | Hard-delete an app-owned collection (Postgres + Qdrant). Body: `{"name": "<short_name>"}`. |
| `POST /grant_rag_access` | Link an app-owned RAG to an app-owned lab (read and/or write). Same effect as the operator UI's Links tab — but for consumer apps. |
| `POST /revoke_rag_access` | Unlink a RAG from a lab. |
| `POST /list_rag_documents` | List documents in an app-owned collection. |
| `POST /ingest_rag_document` | Ingest a text document into an app-owned collection. Default `replace_if_exists=true` deletes any prior document with the same `filename` first, preventing storage bloat on re-ingest. |
| `POST /delete_rag_document` | Delete one document (by `document_id` or all docs matching a `filename`). |

### Direct GPU dispatchers (skip the agent loop)

| Endpoint | Purpose |
|---|---|
| `POST /run` | Submit a ComfyUI workflow JSON, wait for completion, copy outputs. |
| `POST /run_flux_text2img` | Convenience wrapper for Flux.1-Dev. |
| `POST /run_ltx_image2video` | Convenience wrapper for LTX-2.3. |
| `POST /run_ffmpeg_op` | Local ffmpeg ops: `extract_last_frame`, `concat`. |

### Model proxies

| Endpoint | Purpose |
|---|---|
| `POST /transcribe` | STT dispatcher (Whisper). Returns text + per-segment timestamps. |
| `POST /llm_complete` | One-shot or multi-turn chat completion. Routed by the bob-api dispatcher to the least-loaded compatible provider. Pass `model`, `messages` (full conversation history), `temperature`, optional `max_tokens` (default 4096, see below). Stateless — your app holds the conversation state and replays it each turn. No lab needed. Vision-capable models accept image attachments (see below). Function calling is supported via the optional `tools` field (see below). Ollama reasoning models accept `think: false` to skip chain-of-thought (see below). |
| `POST /list_models` | Discover the model identifiers that `/llm_complete` can route to. Body: `{"available_only": true}` (default). Returns `{models: [{model_identifier, available, provider_types, capabilities}]}`. |

### Sending images to a vision model

`/llm_complete` accepts an optional `images` field on any user message. Each
entry is a base64-encoded image (raw, or with a `data:image/...;base64,`
prefix). The dispatcher converts to provider-native format automatically:
Ollama sees the native `images` field; OpenAI-compatible providers (vLLM,
HuggingFace TGI) get OpenAI multimodal `content_parts`.

Pick a vision-capable model (e.g. `kavai/qwen3.5-GPT5:9b`, `llava:*`,
`qwen2-vl:*`). Models without vision support will ignore the images or error.

```json
{
  "model": "kavai/qwen3.5-GPT5:9b",
  "messages": [
    {
      "role": "user",
      "content": "Describe what you see in one sentence.",
      "images": ["iVBORw0KGgoAAAANSUhEUgAA..."]
    }
  ],
  "temperature": 0.1,
  "max_tokens": 300
}
```

A few practical notes:

- The HMAC body signature still covers the entire request, so the image is
  authenticated alongside the prompt. No separate upload step.
- Larger images mean larger bodies and slower HMAC + bigger token counts on
  the model side. Resize/compress on the consumer side before encoding.
- Conversation history is replayed every turn (stateless). If your chat
  references an earlier image, send it again on each turn.

### Controlling output length (`max_tokens`)

`max_tokens` caps how many tokens the model is allowed to generate in a
single response. Default is **4096**. Lower it to fit a UI snippet, raise it
for long-form output. Generation stops as soon as the limit is hit, which
means the response can end mid-sentence — your app should treat it as a
hard ceiling.

```json
{
  "model": "qwen3.6:35b-a3b",
  "messages": [{"role": "user", "content": "Write a 200-word essay on tea."}],
  "max_tokens": 32
}
```

Live numbers on the same prompt:

| `max_tokens` | tokens out | duration | content end |
|---:|---:|---:|---|
| `32` | 32 | 2.8 s | `…become a cultural cornerstone and a symbol of tranquility. Originating in ancient` (truncated) |
| `4096` | 326 | 25.0 s | `…uniting people across borders through its gentle, enduring warmth.` (complete) |

Per-provider behavior:

- **Ollama**: forwarded as `options.num_predict`. Hard ceiling; the model
  stops emitting tokens at the limit.
- **vLLM / HuggingFace TGI**: forwarded as `max_tokens`, but auto-capped to
  the model's `max_model_len` (queried from `/v1/models` and cached) to
  avoid 4xx errors when you ask for more than the context window allows.
  The cap is silent — `tokens_out` will reflect the actual generated count.
- **OpenAI-compatible providers**: forwarded as `max_tokens` verbatim.
- **Anthropic**: forwarded as `max_tokens` verbatim.

A few practical notes:

- Input tokens (`tokens_in`) are not bounded by this field — only the
  output side is capped. If your conversation history is huge, you'll pay
  for it on the input side regardless of `max_tokens`.
- For reasoning models with `think: true`, the chain-of-thought counts
  toward `max_tokens`. If you ask for `max_tokens: 100` on a reasoning
  model, you may exhaust the budget before the final answer starts. Either
  raise it, or set `think: false` (Ollama only).
- Tool-calling responses (`tool_calls`) also count toward the token budget.

### Disabling reasoning (Ollama `think` flag)

Reasoning models served by Ollama (qwen3, deepseek-r1, gpt-oss, etc.) emit a
chain-of-thought before the final answer. For latency-sensitive or cost-
sensitive consumer-app calls, pass `think: false` to skip it:

```json
{
  "model": "qwen3.6:35b-a3b",
  "messages": [{"role": "user", "content": "What is 17 * 23?"}],
  "think": false
}
```

Live numbers on the same prompt against `qwen3.6:35b-a3b`:

| `think` | tokens out | duration | content |
|---|---:|---:|---|
| `false` | 4 | 14.4 s | `"391"` |
| `true` | 268 | 20.6 s | reasoning trace + answer |

Accepted values: `true`, `false`, or `"low"` / `"medium"` / `"high"` for
`gpt-oss`-style models that support graded reasoning. Omit the field to
keep the model's default behaviour.

The flag is **Ollama-only**. vLLM, HuggingFace TGI, OpenAI-compat, and
Anthropic providers silently ignore it — calls don't fail, the field is
just dropped. If you need to suppress reasoning on a non-Ollama provider,
do it via the system prompt instead.

### Function calling (tools)

`/llm_complete` accepts an optional `tools` list using the OpenAI function-
calling schema. Bob-api forwards it to the provider in the right native
format (Ollama's `tools` field for Ollama, OpenAI multipart for vLLM / HF
TGI). When the model decides to call a function, the response includes a
`tool_calls` list — your app dispatches the call, appends the result as a
`{role: "tool", ...}` message, and replays the conversation.

Request:

```json
{
  "model": "qwen3.6:35b-a3b",
  "messages": [
    {"role": "system", "content": "Use tools when relevant."},
    {"role": "user",   "content": "Weather in Paris and Tokyo?"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather for a city",
        "parameters": {
          "type": "object",
          "properties": {"city": {"type": "string"}},
          "required": ["city"]
        }
      }
    }
  ],
  "temperature": 0.1
}
```

Response (when the model emits tool calls):

```json
{
  "content": "...optional reasoning text...",
  "model": "qwen3.6:35b-a3b",
  "provider": "7950x-agent",
  "tokens_in": 299,
  "tokens_out": 94,
  "duration_ms": 23829,
  "tool_calls": [
    {"id": "call_0", "name": "get_weather", "arguments": {"city": "Paris"}},
    {"id": "call_1", "name": "get_weather", "arguments": {"city": "Tokyo"}}
  ]
}
```

Notes:

- The shape is **flat** (`{id, name, arguments}` with `arguments` already
  parsed as a dict), not OpenAI's nested
  `{id, type:"function", function:{name, arguments:"<json string>"}}`.
- If the model returns malformed argument JSON, `arguments` is
  `{"raw_arguments": "<original string>"}` so the call is still inspectable.
- `content` may still contain free-text reasoning the model emitted before
  deciding to call the tool. Treat both fields as available simultaneously.
- A provider that doesn't support tool calling (e.g. vLLM without
  `--enable-auto-tool-choice`) is detected and the call is transparently
  retried without `tools`. In that case `tool_calls` will be absent and the
  model's plain-text reply lands in `content`.
- `tool_calls` is only present when the model emitted at least one call.
  Existing callers that ignore the field see no behavioral change.

To continue the conversation after running the tool, append the assistant's
turn (with its `tool_calls`) and one `tool` message per call:

```json
[
  {"role": "user", "content": "..."},
  {"role": "assistant", "content": "", "tool_calls": [...]},
  {"role": "tool", "tool_call_id": "call_0", "content": "{\"temp_c\": 18}"},
  {"role": "tool", "tool_call_id": "call_1", "content": "{\"temp_c\": 24}"}
]
```

## Lab blueprint

`POST /import_lab` accepts a JSON envelope `{version, lab}`. The `lab` object
describes the orchestrator, agents, tool sets, context files, and (optionally)
RAG access links. Two ways to produce a blueprint:

- **Hand-author** the JSON in your consumer app.
- **Build in the operator UI**, then `GET /api/v1/labs/{lab_id}/export`
  (JWT-auth) to dump the same shape. Hand that JSON to the consumer app.

Minimal example:

```json
{
  "version": 1,
  "lab": {
    "name": "research-loop",
    "description": "Two-agent research + writeup",
    "loop_type": "plan_execute",
    "context_files": [],
    "orchestrator": {
      "model": "qwen3.6:35b-a3b",
      "prompt": "You coordinate two agents to research and write.",
      "temperature": 0.4,
      "tool_sets": []
    },
    "settings": {
      "max_iterations": 6,
      "max_duration_sec": 1200,
      "tool_max_calls": 20,
      "tool_timeout_sec": 60
    },
    "agents": [
      {
        "name": "researcher",
        "role": "Find sources",
        "system_prompt": "Search the KB and return citations.",
        "model": "qwen3.6:35b-a3b",
        "temperature": 0.2,
        "tool_sets": ["web_tools"]
      },
      {
        "name": "writer",
        "role": "Draft the writeup",
        "system_prompt": "Turn the researcher's notes into prose.",
        "model": "qwen3.6:35b-a3b",
        "temperature": 0.6
      }
    ],
    "rag_access": [
      {"collection_name": "app__myapp__product_kb", "can_read": true, "can_write": false}
    ]
  }
}
```

Fields worth knowing:

- `orchestrator.model` / `agents[].model` — by `model_identifier` (the same
  string you'd pass to `/llm_complete`). The dispatcher load-balances across
  whichever providers serve it.
- `tool_sets` — by **name**, not UUID. The names are auto-resolved against
  the operator-managed catalog of tool sets at import time. Names that don't
  match are silently skipped.
- `orchestrator.tools` / `agents[].tools` — list of built-in tool names from
  bob-api's catalog (see [TOOLS_AND_SANDBOX.md](TOOLS_AND_SANDBOX.md)). One
  worth flagging for consumer apps: **`gouv_data_fr`** — read-only access to
  the French open-data catalog (data.gouv.fr datasets, organizations, metrics,
  tabular CSV row queries). No API key needed. Pair it with the
  `templates/skills/datagouv.md` skill by including the file contents in
  `context_files` — your agent will be able to `file_read` it from
  `datagouv_skill.md` for workflow detail.
- `rag_access` — see [RAG](#rag) below. Every entry must reference a
  collection your app already owns (created via `/create_rag`). Cross-app
  refs are rejected with `403`.

### Export → import round-trip

The realistic workflow:

1. An operator builds the lab in the bob-manager UI (Labs page), picking
   models, tools, and agents. They manually link any RAG collections via the
   Links tab.
2. You (the consumer dev) call `GET /api/v1/labs/{lab_id}/export` with an
   operator JWT, save the returned JSON.
3. Recreate the referenced RAG collections under your app via `/create_rag`,
   then edit the exported `rag_access` entries to point at your new
   namespaced names (`app__<app_id>__<name>`).
4. Your consumer app calls `POST /import_lab` with the edited blueprint.
   The lab is created and RAG access rows are materialized in one shot.

Idempotency: `/import_lab` returns the existing lab id if a lab with the same
name already exists (pass `force_refresh: true` to delete and re-import).

## Agents

A **standalone agent** is a reusable agent definition that lives outside any
specific lab. The same operator-managed library that powers the bob-manager
"Agent Library" tab is exposed to consumer apps under their own namespace.
Each app sees only its own agents; the operator UI hides them by default.

When to reach for an agent vs. a lab:

| Need | Use |
|---|---|
| Single-turn LLM call, no state | `/llm_complete` |
| One agent, tool loop, RAG, optional memory | `/run_agent` |
| Multi-agent orchestrator, plan/execute or react loop | `/import_lab` + `/run_lab` |

`/run_agent` spawns an ephemeral single-agent lab under the hood, runs it
through bob-api's `solo_agent` loop — the LabAgent is driven directly with
native tool-calling (no orchestrator JSON layer), so tool errors and prose
responses are non-fatal. The driver then posts a signed callback with the
final assistant message. Use it for chatbots, classifiers, summarizers,
anything that fits one prompt-and-response with optional tool calls.

### Lifecycle

```bash
# Create
POST /api/v1/internal/apps/create_agent
  {
    "name": "kb_assistant",
    "system_prompt": "You answer product questions using rag_search.",
    "model": "qwen3.6:35b-a3b",
    "temperature": 0.2,
    "max_tokens": 1024,
    "tools": ["rag_search"]
  }
→ 201
  {
    "agent_id": "<uuid>",
    "name": "kb_assistant",
    "library_agent_name": "app__myapp__kb_assistant",
    "role": "",
    "system_prompt": "You answer product questions using rag_search.",
    "model": "qwen3.6:35b-a3b",
    "temperature": 0.2,
    "max_tokens": 1024,
    "tools": ["rag_search"],
    "tool_sets": [],
    "cron_expression": null,
    "cron_instruction": "",
    "share_memory": false,
    "anti_loop_enabled": false
  }
```

Like collections, `name` is your short label. The full namespaced
`library_agent_name` is `app__<app_id>__<name>`; this is what surfaces in
the operator UI when an operator opts to see app-owned agents
(`?include_app_owned=true` on `GET /library-agents`).

`/create_agent` is **idempotent**: a second call with the same name
returns the existing agent.

```bash
# List your agents
POST /api/v1/internal/apps/list_agents
→ 200 {"agents": [ … ]}

# Delete (rejected if not owned by you)
POST /api/v1/internal/apps/delete_agent
  {"name": "kb_assistant"}
→ 200 {"deleted": true}
```

### Importing an agent blueprint (full config in one shot)

Use `/import_agent` when you want to push a fully configured agent
(including RAG access) atomically. The blueprint envelope mirrors
`LabBlueprint`:

```json
{
  "version": 1,
  "agent": {
    "name": "kb_assistant",
    "role": "support",
    "system_prompt": "You answer product questions using rag_search. Be terse.",
    "description": "Product KB assistant",
    "model": "qwen3.6:35b-a3b",
    "temperature": 0.2,
    "max_tokens": 1024,
    "tools": [],
    "tool_sets": [],
    "share_memory": false,
    "callable_agents": [],
    "cron_expression": null,
    "cron_instruction": "",
    "anti_loop_enabled": false,
    "rag_access": [
      {"collection_name": "app__myapp__product_kb", "can_read": true, "can_write": false}
    ]
  }
}
```

```bash
POST /api/v1/internal/apps/import_agent
  {"blueprint": <the above>, "force_refresh": false}
→ 201 { ...AgentOut shape... }
```

Behavior is identical to `/import_lab`: idempotent by short name; pass
`force_refresh: true` to delete and re-import. Each `rag_access` entry is
ownership-checked and 403's if it points to another app's collection.

The `rag_access` block is **persisted with the agent**, not just per-run.
Every subsequent `/run_agent` invocation (and every cron firing) re-uses
the same access list — the ephemeral lab gets fresh `LabRagAccess` rows
materialized at spawn time so the agent's `rag_search` / `rag_ingest`
tools are auto-injected by the runner.

### Invoking an agent

```bash
POST /api/v1/internal/apps/run_agent
  {
    "name": "kb_assistant",
    "generation_id": "<your-uuid>",
    "callback_url": "https://my-app/internal/bob-callback",
    "user_message": "What's the maximum operating temperature of the K-7?",
    "context_files": []
  }
→ 202
  {
    "lab_id": "<ephemeral lab uuid>",
    "status": "started"
  }
```

The actual response comes back as a signed callback when the agent
finishes (default timeout: **600 s**, override with the
`APP_AGENT_RUN_TIMEOUT_SEC` env on bob-api). Callback shape:

```json
{
  "generation_id": "<your-uuid>",
  "agent_name": "kb_assistant",
  "status": "completed",
  "output": {
    "content": "The K-7 operates up to 65 °C continuous.",
    "tool_calls": [],
    "tokens_in": 412,
    "tokens_out": 18,
    "duration_ms": 1820,
    "model": "qwen3.6:35b-a3b",
    "provider": "ollama-rtx5"
  }
}
```

On failure: `{generation_id, agent_name, status: "failed", error: "..."}`.

`context_files` follow the same convention as `/run_lab`: each entry is
written into the ephemeral lab's sandboxed workspace so the agent can
`file_read` it from a tool call.

### Cron-scheduled agents

If an agent has a `cron_expression` (set at create/import time, or
patched via a future `/update_agent`), the bob-api scheduler fires it
every tick that the expression matches. Each firing spawns its own
ephemeral lab tagged `app:<app_id>:agent_run:<short>:cron:<tick_iso>` so
runs don't pile on top of each other.

**Cron runs do NOT deliver callbacks** — the scheduler has no
per-firing `callback_url`. Poll instead:

```bash
POST /api/v1/internal/apps/list_agent_runs
  {"name": "kb_assistant", "limit": 20}
→ 200
  {
    "runs": [
      {
        "lab_id": "<uuid>",
        "agent_name": "kb_assistant",
        "triggered_by": "cron",
        "generation_id": null,
        "cron_tick": "2026-05-11T08:00:00+00:00",
        "status": "completed",
        "final_output": "Weekly KB refresh: 14 docs updated, 2 obsolete deleted.",
        "created_at": "2026-05-11T08:00:01+00:00",
        "completed_at": "2026-05-11T08:00:47+00:00"
      }
    ]
  }
```

`final_output` is the agent's last substantive assistant message,
truncated to 4 000 chars. `triggered_by` is `"cron"` for scheduler
firings, `"run_agent"` for HMAC-triggered invocations. Pass an empty
`name` to list runs across every agent owned by this app.

### Limitations

- **One agent per run.** Use `/import_lab` if you need multi-agent
  orchestration with a real plan/execute loop.
- **No streaming.** The callback arrives once the run completes (or fails
  / times out). For partial output, you'd need to extend the runner —
  out of scope for the HMAC surface.
- **Cron-only result delivery is polling.** If you need realtime push for
  cron firings, build a thin wrapper that polls `/list_agent_runs` on a
  short interval and forwards new rows to your consumer-app's webhook.
- **Same-host only.** Agents inherit the consumer-app HMAC channel's
  same-host restriction. No cross-host calls.

## RAG

Bob-api ships a Qdrant-backed RAG. Consumer apps can:

- **Create** their own collections and ingest documents from them via the
  agent runtime.
- **Link** those collections to labs they import — granting the lab's agents
  access to `rag_list_collections`, `rag_search`, and (with `can_write`)
  `rag_ingest` tools.

### Lifecycle

```bash
# Create
POST /api/v1/internal/apps/create_rag
  {
    "name": "product_kb",
    "display_name": "Product knowledge base",
    "description": "Specs and FAQs",
    "embedding_model": "all-MiniLM-L6-v2",
    "distance_metric": "cosine"
  }
→ 201
  {
    "collection_id": "<uuid>",
    "name": "product_kb",
    "collection_name": "app__myapp__product_kb",
    "display_name": "Product knowledge base",
    "embedding_model": "all-MiniLM-L6-v2",
    "embedding_dim": 384,
    "distance_metric": "cosine"
  }
```

`name` is your short label; the response includes the full namespaced
`collection_name` (`app__<app_id>__<name>`) — that's the value to use in any
blueprint's `rag_access` field.

```bash
# List
POST /api/v1/internal/apps/list_rags
→ 200 {"rags": [ … ]}

# Delete
POST /api/v1/internal/apps/delete_rag
  {"name": "product_kb"}
→ 200 {"deleted": true}
```

`/create_rag` is **idempotent**: calling it twice with the same `name`
returns the same collection. Cross-app name reuse is rejected.

### Linking to a lab

There are two ways to grant a lab access to a RAG:

**Via blueprint** (preferred, atomic with `/import_lab`):

```json
"rag_access": [
  {"collection_name": "app__myapp__product_kb", "can_read": true, "can_write": false}
]
```

**Imperatively, after import:**

```bash
POST /api/v1/internal/apps/grant_rag_access
  {
    "lab_id": "<lab uuid>",
    "rag_name": "product_kb",
    "can_read": true,
    "can_write": false
  }
→ 200
  {
    "lab_id": "<lab uuid>",
    "collection_id": "<uuid>",
    "collection_name": "app__myapp__product_kb",
    "can_read": true,
    "can_write": false
  }
```

Both endpoints check that the lab and the RAG are owned by the calling app
(`acl.tag` prefix `app:<app_id>:`). Cross-app references return `403`.

To revoke:

```bash
POST /api/v1/internal/apps/revoke_rag_access
  {"lab_id": "<lab uuid>", "rag_name": "product_kb"}
→ 200 {"revoked": true}
```

### How agents actually use the RAG

Once a lab has any `LabRagAccess` row, bob-api auto-injects three tools into
every agent in that lab:

- `rag_list_collections` — list collections the lab can read
- `rag_search` — semantic search with `top_k`, `score_threshold`, optional
  metadata filter
- `rag_ingest` — present only when at least one row has `can_write: true`

Your agents call these like any other tool. Results carry `document_id`,
`source`, `text`, `score`, `chunk`, and `metadata`.

### Ingesting documents

Three paths, depending on what your app is doing:

1. **HMAC `/ingest_rag_document`** — push raw text inline. The right call
   for managed KBs the app keeps fresh on its own schedule (extracted page
   text, JSON-derived prose, periodic syncs). **Default behavior is upsert
   by filename**: any prior document with the same `filename` is deleted
   before the new one is ingested. Pass `replace_if_exists=false` to keep
   versions cohabiting.

   ```bash
   POST /api/v1/internal/apps/ingest_rag_document
     {
       "name": "product_kb",
       "filename": "EU_2018_848.txt",
       "content": "<extracted text>",
       "metadata": {"source_url": "https://...", "fetched_at": "2026-05-11"},
       "replace_if_exists": true
     }
   → 201
     {
       "document_id": "<uuid>",
       "filename": "EU_2018_848.txt",
       "status": "ready",
       "chunk_count": 42,
       "replaced_previous": true
     }
   ```

   Pair with `POST /list_rag_documents {"name": "..."}` to inspect the
   collection and `POST /delete_rag_document {"name": "...", "filename": "..."}`
   to clean up duplicates accumulated before `replace_if_exists` was wired
   in (every doc matching `filename` is deleted at once).

2. **From inside a lab/agent run**, the `rag_ingest` tool (available when
   the agent has `can_write`) ingests strings into the collection. Useful
   when an agent is itself producing the content (research notes, extracted
   summaries) during execution.

3. **Via the operator UI's file upload** flow at
   `/rag/collections/{id}/documents` — drag-and-drop PDFs, Office files,
   etc. Use this when a human is curating the KB. Files are routed through
   the same content extractor `/ingest_rag_document` uses.

The HMAC ingest endpoint is text-only by design. For PDFs and other
binary formats, use path 3 (operator UI) which runs the binary extractor
chain.

### Single-shot agents (an alternative to running a whole lab)

`/llm_complete` is a stateless LLM completion — no RAG, no tools, no
memory. For one-off interactive flows where you do need RAG + tools +
optional persistence but a full lab is overkill, register a standalone
agent via `/create_agent` (or `/import_agent`) and call `/run_agent`. The
agent is invoked in an ephemeral single-agent lab that mirrors the lab
runtime: tool loop, RAG auto-injection (from `rag_access`), persistent
memory across runs (if `share_memory=true`). See [Agents](#agents).

## Limitations and ownership

- **Naming** — collection short names are alphanumeric + `_` + `-` only. The
  full namespaced name is `app__<app_id>__<name>` (always); use this exact
  string in blueprint `rag_access` entries.
- **Cross-app isolation** — every RAG endpoint enforces that the referenced
  collection (and, for `grant_rag_access`, the referenced lab) carries an
  `acl.tag` prefixed with the calling app's id. Other-app or operator-owned
  resources are invisible.
- **Operator UI hiding** — `GET /api/v1/rag/collections` filters out
  `app:*:rag:*`-tagged rows by default. Pass `?include_app_owned=true` to
  surface them (same convention as `?include_app_runs=true` on labs).
- **Vector-only for now** — `/create_rag` provisions vector-mode collections
  (Qdrant). LightRAG-mode collections still need to be created via the
  operator UI.

## Webhook callbacks

Long-running endpoints (lab runs, ComfyUI dispatches) accept a `callback_url`
and respond immediately. When the work finishes, bob-api POSTs back to that
URL with the same HMAC-signed envelope (using **the consumer app's secret** —
mutual auth):

```json
{
  "generation_id": "<your-uuid>",
  "status": "completed | failed",
  "output_path": "/data/app_uploads/<app_id>/<generation_id>/<file>",
  "error": "..."
}
```

Retry policy: 3 attempts with exponential backoff (~14 s total). After that,
bob-api logs and drops; the consumer app must reconcile via a sweeper or
admin tool.

## Shared filesystem

Generation artifacts are written to a named Docker volume mounted on **both**
containers:

- bob-api: `/data/app_uploads/<app_id>/...` (RW)
- consumer-api: same path (RO is sufficient)

The consumer app reads files directly from disk. There is no HTTP file
endpoint — the named volume is the contract.

## ACL tags

Bob-api tags every consumer-app-scoped resource so the operator UI can hide
them by default while still being able to surface them on demand:

| Resource | Tag form | Surfaces with |
|---|---|---|
| Imported lab template | `app:<app_id>:template:<name>` | `?include_app_runs=true` on `GET /labs` |
| `/run_lab` cloned lab | `app:<app_id>:run:<generation_id>` | `?include_app_runs=true` on `GET /labs` |
| `/run_agent` ephemeral lab | `app:<app_id>:agent_run:<short>:<generation_id>` | `?include_app_runs=true` on `GET /labs` |
| Cron agent firing | `app:<app_id>:agent_run:<short>:cron:<tick_iso>` | same |
| RAG collection | `app:<app_id>:rag:<name>` | `?include_app_owned=true` on `GET /rag/collections` |
| Standalone agent (library_agent) | name-based: `app__<app_id>__<name>` (UNIQUE) | `?include_app_owned=true` on `GET /library-agents` |

`library_agents` has no `acl` column today, so agent ownership is encoded
in the (UNIQUE) name prefix `app__<app_id>__`. Everything else uses
`acl.tag`.

## Filesystem layout for a consumer-app repo

The recommended shape:

```
my-consumer-app/
├── app-api/                     # FastAPI backend (your business logic)
│   └── app/
│       ├── services/bob_client.py   # HMAC client to bob-api
│       └── api/routes/...           # endpoints your UI calls
├── app-ui/                      # React/Next/whatever frontend
├── docker-compose.yml           # joins bob-api's network as external
├── .env.example                 # BOB_API_URL, BOB_APP_ID, BOB_APP_SECRET
└── README.md
```

The compose file should:

- declare bob-api's network as `external: true`
- declare the `app_uploads` volume as `external: true`
- mount the volume into your container at the same path bob-api uses

## What does NOT cross the boundary

The consumer app **must not** reach into bob-api's database, Qdrant, or lab
filesystem directly. Everything goes through the documented HTTP surface.
This keeps bob-api releasable and upgrade-safe.

If you find yourself wanting a primitive that doesn't exist yet, the right
move is to add a generic endpoint to bob-api — not a special case for your
app.

## Related

- [API_REFERENCE.md](API_REFERENCE.md) — full request/response shapes for the `/internal/apps/*` endpoints
- [CONFIGURATION.md](CONFIGURATION.md) — env-var reference
