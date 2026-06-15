# Hermes Adapter — API contract

The Bob Lab control-plane drives the **real NousResearch Hermes agent**
([nousresearch/hermes-agent](https://github.com/nousresearch/hermes-agent)) as an
agent backend (`LabAgent.backend == 'hermes'`). Hermes has no HTTP API of its own
(CLI + messaging gateway only), so each per-agent container runs Hermes **plus this
adapter**: a small FastAPI wrapper around Hermes' Python entrypoint that exposes the
endpoints below.

The control-plane side is already implemented and tested against this contract
(`control-plane/app/services/hermes/`). Build the image, set `HERMES_IMAGE`, and the
feature lights up — no further control-plane changes needed.

## Container expectations

- Listens on **port 8770** (matches `HERMES_INTERNAL_PORT`, default `8770`).
- Persists ALL Hermes state under **`/root/.hermes`** — the control-plane mounts a
  named volume there (`bob-hermes-<agent-id>`); memory/skills/sessions must survive
  container restarts and re-creates.
- No messaging gateway needed (`hermes gateway` stays off); Bob Lab is the only client.
- Single-tenant: one container per Bob Lab agent. The control-plane serializes
  `/v1/agent/run` calls per container — the adapter may also guard with its own lock.
- Start fast enough to pass `GET /health` within ~90s of container start.

## Endpoints

### `GET /health`
`200 {"status": "ok"}` once Hermes is initialized and able to take a task.

### `GET /v1/info`
```json
{ "hermes_version": "x.y.z", "tools": ["web_search", "..."] }
```
Diagnostic only — shown in the UI later; keep it cheap.

### `POST /v1/agent/run`
Run **one full agent turn** (Hermes' own loop: think → tools → … → final reply) and
return the final reply. Request:

```json
{
  "system_prompt": "operator-authored persona/instructions (may be empty)",
  "instruction":   "the task for this turn",
  "history":       [{"role": "user|assistant", "content": "..."}],
  "model": {
    "provider_type":    "ollama | openai | anthropic | huggingface | ...",
    "base_url":         "http://192.168.x.x:11434",
    "api_key":          "secret-or-null",
    "model_identifier": "qwen2.5:14b"
  },
  "options": {}
}
```

Contract points:
- **`model` arrives on EVERY request** and must be applied to Hermes *before* the turn
  (via `hermes config set` / provider config / env — whatever the installed Hermes
  version supports). This is how the operator switches Hermes' LLM live from the Bob
  Lab dropdown — no container restart. Map `provider_type` to Hermes' provider naming
  (e.g. `ollama` → an OpenAI-compatible local endpoint `{base_url}/v1`, `openai` →
  OpenAI-compatible, `anthropic` → Anthropic). Unknown types: return 400 with a clear
  message.
- `history` is optional context (recent lab transcript); v1 control-plane sends `[]` —
  Hermes' own session memory carries continuity.
- `options` keys understood: `max_iterations` (Hermes loop cap per turn, default 30),
  `max_continuations` (task-completion rounds, default 6), `session_id` (default `boblab`).
  Ignore unknown keys.
- Run synchronously; the control-plane waits up to `HERMES_DEFAULT_TIMEOUT_SEC`
  (default **900s**). Long turns are expected.

**Task-completion protocol (the two-loops problem).** Hermes ends a turn whenever the
model emits text without tool calls — including mid-work narration ("let me browse…").
Bob Lab's lab loop must only re-engage when the *task* is done, so the adapter runs each
task as a continuation loop on ONE in-memory `AIAgent`:

1. The first message carries the task plus a protocol footer instructing Hermes to end
   with a final line `TASK_DONE` when fully complete, or `NEEDS_INPUT: <question>` when
   blocked on the operator.
2. If a turn ends without either marker, the adapter sends `continue` to the same agent
   (up to `max_continuations` rounds) — Hermes resumes its own work in-session.
3. The final reply is returned once: `TASK_DONE` is stripped from the content;
   a `NEEDS_INPUT` line is kept so the operator sees the question. Each round appears in
   `steps` (`{type: "turn", round, exit_reason, api_calls, task_done, needs_input}`).

Response `200`:

```json
{
  "content": "Hermes' final reply for the turn (required, plain text/markdown)",
  "usage":   {"tokens_in": 123, "tokens_out": 456},
  "steps":   [{"type": "tool", "name": "web_search", "summary": "..."}]
}
```
`usage` and `steps` are optional (defaulted to zero/empty by the control-plane).
Errors: any non-2xx with a JSON `{"detail": "..."}` body; the message is surfaced
verbatim to the operator in the lab transcript.

## Image sketch

```
hermes-adapter/
├── Dockerfile          # python base → install hermes-agent → install adapter
├── adapter/
│   └── main.py         # FastAPI app implementing this contract
└── ADAPTER_CONTRACT.md # this file
```

Suggested build steps (Dockerfile stub in this directory):
1. `pip install` Hermes per upstream instructions (or clone + install).
2. `hermes setup` non-interactively / pre-seed `~/.hermes` config with tools enabled,
   gateway disabled.
3. Install the adapter (FastAPI + uvicorn) and run it as PID 1 on port 8770.
4. The adapter invokes Hermes in-process (its Python entrypoint, e.g. the module
   behind `run_agent.py`) or via a PTY-driven CLI session — in-process is strongly
   preferred for reliable reply capture.

## Control-plane configuration (already wired)

| Env var | Default | Meaning |
|---|---|---|
| `HERMES_IMAGE` | *(empty = feature off)* | Image name for the per-agent container |
| `HERMES_DEFAULT_TIMEOUT_SEC` | `900` | Max wait per turn |
| `HERMES_INTERNAL_PORT` | `8770` | Adapter port inside the network |
| `HERMES_MEM_MB` / `HERMES_CPUS` | `2048` / `2.0` | Container resources |

Smoke test once the image exists: tag it, set `HERMES_IMAGE`, restart bob-api, open
the seeded **“Hermes (Nous) — Real Agent”** library agent, pick a model, click
Activate, create an instance, inject a task.
