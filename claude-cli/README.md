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

## Endpoint contract

| Endpoint | Behaviour |
|---|---|
| `GET /health` | `{status, claude_version, token_present, models}`; `?deep=true` runs a real one-shot to verify the token |
| `GET /v1/models` | OpenAI list shape; ids = `claude-cli:` + each entry of `CLAUDE_CLI_MODELS` |
| `POST /v1/chat/completions` | One `claude -p --output-format json --max-turns 1` per request. Accepts `claude-cli:opus` or bare `opus`. `stream:true` → SSE (single content chunk, stop chunk with usage, `[DONE]`). Errors: 400 unknown model, 502 CLI failure (detail surfaces in lab transcripts), 504 timeout |

**Text-only (v1):** `tools` are accepted and ignored, images dropped. Don't
assign tools to agents using these models.

System messages become `--system-prompt`; a multi-turn history is flattened
into a transcript prompt. Each request is a fresh subprocess, bounded by
`CLAUDE_CLI_CONCURRENCY` (the control plane dispatches at most 2 concurrent
requests per provider).

## Security notes

- Runs as non-root user `claude`; no workspace is mounted — the CLI runs
  with all built-in tools disallowed and `--max-turns 1`.
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
