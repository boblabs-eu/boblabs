# Claude CLI model provider (GPU-server sidecar)

Runs Claude Code CLI behind a small OpenAI-compatible HTTP wrapper so the
fleet can use Claude models through your **Max subscription** (no API
credits). One container per GPU server — exactly the role Ollama plays on
port 11434:

```
GPU server                          Control plane
┌─────────────────────────────┐
│ claude-cli wrapper :3021    │◄── inference (LabDispatcher →
│   └─ claude -p one-shots    │     OpenAICompatibleProvider)
│ bob agent                   │
│   └─ probes /v1/models ─────┼──► websocket metrics → AIProvider/AIModel
└─────────────────────────────┘     (pending admin approval)
```

Models appear in the UI as `claude-cli:opus`, `claude-cli:haiku`, … — the
`claude-cli:` namespace keeps them visibly distinct from Anthropic **API**
models (different billing, different path), and prevents the model list from
ever merging the two.

The wrapper serves the same Claude tiers in **three modes**, distinguished by
prefix — `claude-cli:` (text-only), `claude-bridge:` (drives the *caller's*
tools), and `claude-agent:` (Claude Code's *own* tools). They all bill against
your Max subscription; none use API credits. See
[Three modes](#three-modes-claude-cli-vs-claude-bridge-vs-claude-agent) for
which to pick.

## 1. One-time auth (on a machine WITH a browser)

```bash
claude setup-token
```

This runs the OAuth flow and prints a token starting with `sk-ant-oat01-`,
tied to your Max plan. Copy it into `.env`:

```bash
cp .env.example .env
# paste the token into CLAUDE_CODE_OAUTH_TOKEN
```

The token is injected at runtime — nothing secret is baked into the image.

## 2. Configure models (.env — the single source of truth)

```bash
CLAUDE_CLI_MODELS=haiku,opus,sonnet
```

Bare aliases (`haiku`, `opus`, `sonnet`) always track the **latest** model of
each tier. Pin an exact id (e.g. `claude-opus-4-8`) for a fixed version. The
wrapper never hardcodes the list — edit `.env` and `docker compose up -d` to
apply.

Two more **opt-in** lists expose the same tiers in the other modes (empty by
default — see [Three modes](#three-modes-claude-cli-vs-claude-bridge-vs-claude-agent)):

```bash
CLAUDE_CLI_BRIDGE_MODELS=opus     # also serves claude-bridge:opus
CLAUDE_CLI_AGENT_MODELS=opus      # also serves claude-agent:opus
```

## 3. Build & run

```bash
docker compose up -d --build
```

Smoke tests:

```bash
curl -s localhost:3021/health | jq            # status, version, token_present, models
curl -s "localhost:3021/health?deep=true" | jq # real auth round-trip (burns one request)
curl -s localhost:3021/v1/models | jq
curl -s localhost:3021/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"claude-cli:haiku","messages":[{"role":"user","content":"say hi"}]}' | jq
# streaming (what the control plane uses):
curl -sN localhost:3021/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"claude-cli:haiku","messages":[{"role":"user","content":"say hi"}],"stream":true}'
```

## 4. Wire it to the fleet

On the same GPU server, point the bob agent at the wrapper (default already
matches):

```bash
# /etc/bob-agent.env
CLAUDE_CLI_URL=http://localhost:3021
```

Restart the agent. Within one metrics tick the control plane auto-discovers
the provider `claude_cli-<agent-name>` (**pending admin approval** — like any
auto-discovered provider). Approve it in Orchestrator → Providers, and the
models show up in the Lab/Agent model dropdowns.

## Three modes: `claude-cli` vs `claude-bridge` vs `claude-agent`

The wrapper exposes Claude in three shapes. Pick by **who runs the agent loop
(the "harness") and whose tools you want.** All three use the Max subscription —
no API credits.

| | `claude-cli:*` | `claude-bridge:*` | `claude-agent:*` |
|---|---|---|---|
| **What it is** | Pure TEXT model | A tool-calling brain for *your* harness | A full Claude Code agent |
| **Who runs the loop** | the caller (lab / Hermes) | the caller (Hermes) | Claude Code itself |
| **Whose tools** | none (caller executes) | **the caller's** (Hermes' `terminal`/`browser`/`memory`/…) | **Claude Code's own** (`Bash`/`WebSearch`/`Write`/`Task`/…) |
| **Incoming `tools`** | dropped | **kept** → described to Claude → parsed back as structured `tool_calls` | ignored (uses its own) |
| **`claude -p` flags** | `--max-turns 1 --tools ""` | `--max-turns 1 --tools ""` + tools as text | `--max-turns 40 --dangerously-skip-permissions` |
| **Returns** | text | `tool_calls` (or text when done) | final text after doing the work |
| **Turns / request** | 1 | 1 (caller loops) | many (self-driving) |

### When to use which

- **`claude-cli:*`** — the original. The **lab orchestrator** is the brain and
  Bob drives tools via the `<tool_call>` *text* protocol it parses itself.
  Correct for **native lab agents**. **Do NOT give it to a Hermes agent** —
  Hermes expects *structured* tool calls, gets none, and the model will
  **hallucinate** tool results (confident fake data — e.g. a made-up weather
  forecast with no real fetch).

- **`claude-bridge:*`** — when you want **opus to drive a *Hermes* agent's own
  tools** on the Max sub. The wrapper keeps the schemas Hermes sends, describes
  them to Claude as text + the `<tool_call>` protocol, and parses Claude's
  output back into **structured** `tool_calls` Hermes executes. **Hermes stays
  the harness** — SOUL, memory, skills, and its ~25 in-container tools intact
  (incl. the **keyless `browser_*`** toolset the adapter image ships — see
  [docs/HERMES.md → Tools available in the adapter](../docs/HERMES.md#tools-available-in-the-adapter)).
  This is the Max-sub equivalent of "native Hermes + Claude API." Tradeoff: a
  text-protocol shim, slightly less robust than true native function-calling.

- **`claude-agent:*`** — when you want **Claude Code itself to be the agent**: it
  thinks, uses *its own* tools (Bash, WebSearch, WebFetch, Read/Write/Edit, Task
  subagents), multi-turn, and returns the result. Most capable for general work,
  but it is **not** a Hermes agent — no Hermes SOUL/memory/skills (it uses Claude
  Code's own `CLAUDE.md` + session). The control plane routes a `claude-agent:*`
  agent straight to the wrapper and takes the final text (no Bob tool loop).

### How this maps to a Hermes setup

Install Hermes from its own repo, point it at a model provider, and opus drives
**Hermes' tools** — *provided the brain (a) accepts tool schemas and (b) returns
structured tool calls.* That requirement is the whole story:

| Hermes brain | Drives Hermes' tools? | Cost | Mechanism |
|---|---|---|---|
| **Anthropic API** (`claude-opus-4-8`) | ✅ native `tool_use` | API credits | Messages API returns structured calls |
| **`claude-bridge:opus`** (this wrapper) | ✅ via `<tool_call>` text shim | **Max sub** | wrapper translates text → structured |
| **`claude-cli:opus`** | ❌ text-only → **hallucinates** | Max sub | `tools` dropped; no real calls |
| **`claude-agent:opus`** | ❌ uses Claude Code's *own* tools | Max sub | Claude Code is the harness, not Hermes |
| **Ollama** (`qwen3.6:35b`) | ✅ native `tool_calls` | free / local | Ollama returns structured calls |

**Bottom line:** to get the native-Hermes-with-opus experience *inside Bob*
without paying for the API, set the Hermes agent's brain to **`claude-bridge:opus`**.
For Claude doing its own thing (its own tools + subagents), use
**`claude-agent:opus`**. Reserve **`claude-cli:*`** for native lab agents where
the orchestrator is the brain.

## Endpoint contract

| Endpoint | Behaviour |
|---|---|
| `GET /health` | `{status, claude_version, token_present, models}`; `?deep=true` runs a real one-shot to verify the token |
| `GET /v1/models` | OpenAI list shape; ids = `claude-cli:`/`claude-bridge:`/`claude-agent:` × each configured tier |
| `POST /v1/chat/completions` | One `claude -p --output-format stream-json` per request; flags vary by mode (`--max-turns 1` for cli/bridge, `--max-turns 40 --dangerously-skip-permissions` for agent). Accepts a namespaced id or bare `opus`. `stream:true` → SSE (one content-or-`tool_calls` chunk, finish chunk with usage, `[DONE]`). Errors: 400 unknown model, 502 CLI failure (detail surfaces in lab transcripts), 504 timeout |

**Modes by prefix:** `claude-cli:*` is text-only (`tools` accepted but ignored —
don't assign tools to agents on these). `claude-bridge:*` keeps `tools` and
returns structured `tool_calls`; `claude-agent:*` runs Claude Code's own tools
multi-turn. Images are dropped in all modes. See
[Three modes](#three-modes-claude-cli-vs-claude-bridge-vs-claude-agent).

System messages become `--system-prompt`; a multi-turn history is flattened
into a transcript prompt. Each request is a fresh subprocess, bounded by
`CLAUDE_CLI_CONCURRENCY` (the control plane dispatches at most 2 concurrent
requests per provider).

## Security notes

- Runs as non-root user `claude`. In `claude-cli`/`claude-bridge` modes the CLI
  runs with all built-in tools disallowed and `--max-turns 1`. **`claude-agent`
  mode enables Claude Code's own tools** (Bash, Write, …) with
  `--dangerously-skip-permissions` and multi-turn — safe because it's confined to
  this non-root container; only enable `CLAUDE_CLI_AGENT_MODELS` if you accept
  that the agent can run commands inside the container.
- Unauthenticated by default, like Ollama: firewall port 3021 so only the
  control-plane host can reach it, or set `CLAUDE_CLI_API_KEY` and put the
  same value in the provider's `api_key` field in the UI.
- Keep `.env` out of git. Rotate the token with `claude setup-token` if it
  leaks; revoke old sessions in Claude account settings.

## Subscription vs API

Running **your own** Claude Code invocations on your own servers via
`claude setup-token` is the supported first-party path for a Max plan, and it
is rate-limited by your plan. If Claude ever serves *a product shipped to
other users*, Anthropic expects an API key — in that case add an Anthropic
provider in the UI instead (those models appear WITHOUT the `claude-cli:`
prefix, so the two are never confused).
