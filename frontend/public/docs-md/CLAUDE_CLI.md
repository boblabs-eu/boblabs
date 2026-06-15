# Bob Labs — Claude CLI Model Provider

Offer Claude models to the fleet through **Claude Code CLI** and a **Max subscription** (no API credits). Unlike Hermes — a per-agent *backend* with its own loop — Claude CLI is a **per-server model provider, exactly like Ollama**: a sidecar container on a GPU server, discovered by the bob agent, synced into the shared model list, and dispatched through `LabDispatcher`.

## Concept

Claude CLI has no HTTP server and no model-list API, so the sidecar (built from [claude-cli/](../claude-cli/)) runs the CLI behind a small **OpenAI-compatible wrapper**. The control plane reuses the generic `OpenAICompatibleProvider` client — no new dispatch code.

```
GPU server                                Control plane
┌────────────────────────────────┐
│ claude-cli wrapper :3021       │◄────── inference: LabDispatcher
│   └─ one `claude -p` per req   │         └─ OpenAICompatibleProvider
│ bob agent                      │         (load balancing, slots,
│   └─ GET /v1/models ───────────┼──►      failover, LLM-event feed)
│      websocket agent.metrics   │
│      "claude_cli_models" ──────┼──► _sync_claude_cli_models
└────────────────────────────────┘      └─ AIProvider claude_cli-<agent>
                                           (pending admin approval)
                                        └─ AIModel claude-cli:opus, …
```

## Model identifiers — the `claude-cli:` namespace

Every identifier the wrapper reports is namespaced: `claude-cli:opus`, `claude-cli:haiku`, `claude-cli:sonnet`. The UI renders `model_identifier` everywhere (dropdowns, synced-models list, LLM-event feed), so the tag is visible at every selection point — and a Claude CLI model can never merge with an Anthropic **API** model (`claude-opus-…`, no prefix) in the deduplicated model list. Different billing, different path, visibly different name.

The model list itself is **configured in the wrapper's `.env`, never hardcoded**:

```bash
CLAUDE_CLI_MODELS=haiku,opus,sonnet     # default — aliases track the latest model
CLAUDE_CLI_MODELS=claude-opus-4-8       # or pin an exact version
```

## Setup (per GPU server)

1. On a machine **with a browser**: `claude setup-token` → token starting `sk-ant-oat01-` (tied to your Max plan).
2. On the GPU server:
   ```bash
   cd claude-cli/
   cp .env.example .env        # paste CLAUDE_CODE_OAUTH_TOKEN
   docker compose up -d --build
   curl -s "localhost:3021/health?deep=true"   # real auth round-trip
   ```
3. Point the bob agent at it (default already matches): `CLAUDE_CLI_URL=http://localhost:3021` in `/etc/bob-agent.env`, restart the agent.
4. Within one metrics tick the provider `claude_cli-<agent-name>` appears in Orchestrator → Providers, **pending admin approval** (like every auto-discovered provider). Approve it; the models join the Lab/Agent model dropdowns.

## The wrapper (inside the image)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | `{status, claude_version, token_present, models}`; `?deep=true` runs one real CLI round-trip |
| `/v1/models` | GET | OpenAI list shape; ids = `claude-cli:` + each `CLAUDE_CLI_MODELS` entry |
| `/v1/chat/completions` | POST | One `claude -p --output-format json --max-turns 1` subprocess per request; SSE streaming and plain JSON |

Mechanics: system messages → `--system-prompt`; multi-turn histories are flattened into a transcript prompt; the prompt travels via stdin (no ARG_MAX limit); `--tools ""` disables built-in tools and `--strict-mcp-config` ignores any ambient MCP servers, so a one-shot behaves as a plain LLM call. The wrapper reads `--output-format stream-json` and, if the model emits a native `tool_use` anyway, converts it into the lab's `<tool_call>` text (see [Why tools are disabled](#why-tools-are-disabled---tools----strict-mcp-config)). Errors surface as `{"detail": …}` and show up verbatim in lab transcripts (502 CLI failure, 504 timeout, 400 unknown model).

| Env var | Default | Meaning |
|---------|---------|---------|
| `CLAUDE_CODE_OAUTH_TOKEN` | — (required) | From `claude setup-token`; bills the Max subscription |
| `CLAUDE_CLI_MODELS` | `haiku,opus,sonnet` | The model list (single source of truth) |
| `CLAUDE_CLI_PORT` | `3021` | Host port (keep in sync with the agent's `CLAUDE_CLI_URL`) |
| `CLAUDE_CLI_CONCURRENCY` | `2` | Max concurrent `claude -p` subprocesses |
| `CLAUDE_CLI_TIMEOUT_SEC` | `300` | Per-request timeout (stay under the dispatcher's 600 s read timeout) |
| `CLAUDE_CLI_TOOLS` | *(empty)* | Native tools available per call, passed to `claude --tools`. Empty = disable **all** tools (the model stays a pure text brain; the lab drives tools). Set names only to allow native tools (rare). |
| `CLAUDE_CLI_API_KEY` | *(empty)* | If set, `/v1/*` requires this Bearer token; mirror it in the provider's `api_key` field |

## Dispatch

`provider_type = "claude_cli"` maps to `OpenAICompatibleProvider` in `create_provider()` with a concurrency slot of **2** in `LabDispatcher` (the wrapper's own semaphore is the hard cap). Load balancing, caller affinity, failover, and the LLM-event feed all work unchanged — if two GPU servers run the wrapper, requests for `claude-cli:opus` balance across both.

## Limitations (v1)

- **Text-only at the OpenAI layer.** The wrapper never returns OpenAI `tool_calls`; agents drive tools via the `<tool_call>` TEXT protocol. If the model emits a native `tool_use` anyway, the wrapper recovers it into `<tool_call>` text (see [Why tools are disabled](#why-tools-are-disabled---tools----strict-mcp-config)), so tool-using lab agents work — not just tool-less ones.
- `temperature` / `max_tokens` have no CLI equivalent and are ignored.
- Images in multimodal messages are dropped with a warning.
- Throughput is subscription-rate-limited and each request is a fresh CLI subprocess — expect seconds, not milliseconds. Prefer `claude-cli:haiku` for chatty loops.

## Why tools are disabled (`--tools "" --strict-mcp-config`)

The lab — not the model — owns tool execution: the model only emits `<tool_call>`
TEXT blocks, and the control plane runs them in the lab sandbox with platform
tools (`gouv_data_fr`, `file_read`/`file_write` on the lab workspace,
`python_exec`, `call_agent`, …). Claude Code's *native* tools can't help here —
they'd run inside the throwaway wrapper container (no lab workspace, no
`gouv_data_fr`) and the result would be discarded. Worse, because the wrapper
runs `claude -p --max-turns 1`, a native `tool_use` spends the single turn and
the call aborts with `error_max_turns`.

A model has **two** tool sources, and both must be shut off:

- **built-in tools** (`Write`, `Bash`, `Task`, …) → removed by `--tools ""`
  (an empty available-tool list).
- **MCP server tools** → removed by `--strict-mcp-config`, which ignores every
  ambient MCP configuration (the persisted `~/.claude` volume, a project
  `.mcp.json`, …). With no `--mcp-config` passed, that loads **zero** MCP servers.

`--tools ""` alone is **not** enough — it does not touch MCP tools, so a stray
MCP server left in the container's `~/.claude` volume still leaks tools, the
model emits a native `tool_use`, and the call dies with `error_max_turns`. The
wrapper therefore always passes **both** flags to keep Claude a pure text brain.

**Disable native tools at the CLI level only — never in the prompt.** The
wrapper passes the caller's system prompt through *verbatim*. A lab's prompt
teaches the model the platform `<tool_call>` TEXT protocol and asks it to call
tools like `gouv_data_fr`; appending something like "do not use tools" to that
prompt contradicts the task, and the model can't tell the lab's text protocol
from native tools — so it either refuses to act ("tool access is not available
in this turn") or flails into a native `tool_use`. Keep the suppression in
`--tools ""` / `--strict-mcp-config`, not in the prompt.

**Recovery fallback.** Even then, opus is trained toward native function-calling
and on large, tool-heavy prompts will *occasionally* emit a native `tool_use`
despite `--tools ""` (whether it does is server-flag dependent — it shows up on
the deployed account but may not reproduce on another machine). It can't execute
(no tools are defined), so the turn would abort as `error_max_turns`. To be
robust, the wrapper reads `--output-format stream-json` and **converts any native
`tool_use` block into the lab's `<tool_call>` text**. With no native tools
defined the model names the tool from the prompt (the lab's own `file_read` /
`gouv_data_fr` / …), so the recovered call is faithful and the lab executes it
normally — both response shapes work and `error_max_turns` is no longer fatal.

(To instead let Claude run its *own* agentic loop with its own tools, that's a
separate **agent backend** — see [HERMES.md](HERMES.md) for the equivalent pattern.)

## Troubleshooting

**`claude CLI tried to use a native tool ...`** (older builds: raw
`error_max_turns` / `stop_reason:"tool_use"`) — a tool slipped past the
text-only wrapper, so the model emitted a native `tool_use` and the single
`--max-turns 1` turn aborted. The wrapper disables built-ins with `--tools ""`
**and** ambient MCP with `--strict-mcp-config`; if you still hit this, an MCP
server is configured *inside* the container. Confirm and reproduce/verify the
fix in-container (no rebuild needed for this check):

```bash
docker compose exec claude-cli claude mcp list          # expect: no servers
docker compose exec claude-cli bash -lc 'printf "Use the Write tool to create /tmp/x.txt, or reply NOTOOLS if you have none." | claude -p --output-format json --model sonnet --max-turns 1 --tools "" --strict-mcp-config' | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('subtype'), d.get('stop_reason'))"
# expect: success end_turn   (a leak would print: error_max_turns tool_use)
```

**Agent replies but refuses to use tools** ("tool access is not available in
this turn", "RUN STAYS STOPPED", no `<tool_call>` emitted) — an older wrapper
build appended "do not use tools" to the system prompt, which the model obeys
literally and so stops following the lab's `<tool_call>` protocol. Fixed by
passing the lab's system prompt through verbatim (native tools are suppressed
only via `--tools ""` / `--strict-mcp-config`). Rebuild from current source.

**`claude CLI error: Permission deny rule "<X>" matches no known tool`** — an
older wrapper build used a `--disallowedTools` denylist with a name the installed
Claude CLI no longer knows (e.g. the removed `MultiEdit`). Rebuild from current
source, which uses `--tools ""` instead of a denylist.

The control plane surfaces the wrapper's real error **body** in a lab's failure
reason, so the underlying Claude CLI error is always visible.

## Subscription vs API

Running **your own** Claude Code invocations on your own servers via `claude setup-token` is the supported first-party path for a Max plan. If Claude serves *a product shipped to other users*, Anthropic expects an API key — add an **Anthropic (Claude)** provider in the UI for that instead; its models appear without the `claude-cli:` prefix, so the two paths stay visibly distinct.
