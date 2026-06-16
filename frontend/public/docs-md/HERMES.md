# Bob Labs — Hermes Agent Backend

Run the real [NousResearch Hermes agent](https://github.com/NousResearch/hermes-agent) as a first-class Bob Labs agent. Hermes is **an agent, not a model**: it owns its own reasoning loop, 40+ tools, persistent memory, and self-improving skills. Bob Labs drives it from the existing agent UI — same form, same model dropdown, usable solo or inside any Lab next to native agents.

## Concept — the `backend` discriminator

Every agent (library template and lab agent) carries a `backend` field:

| Backend | Meaning |
|---------|---------|
| `native` (default) | Bob Labs drives the LLM loop: prompt assembly, hybrid tool calling, bounded tool loop. Unchanged behavior. |
| `hermes` | The whole task is delegated to a dedicated per-agent **Hermes container**, which runs its own loop and tools, then returns one final result. |

The agent's existing `model_id` keeps its meaning for both backends — for Hermes it is **the LLM Hermes thinks with**, picked from the normal model dropdown and switchable at any time (applied per task, no container restart).

```
Lab turn for a hermes-backed agent:

  lab_runner._call_agent
    └─ backend == 'hermes'?
         ├─ ensure container  ──►  bob-hermes-<id>  (popped lazily or via Activate)
         ├─ resolve model_id  ──►  model_identifier (gateway mode)
         ├─ POST /v1/agent/run ──► adapter drives Hermes' own loop
         │                          (continuation rounds until TASK_DONE)
         │     └─ every Hermes model call ──► bob-api /llm-gateway/{agent}/v1
         │                                      └─ LabDispatcher: load balancing,
         │                                         concurrency slots, failover,
         │                                         LLM-event feed
         └─ result → lab message (+ "Hermes flow" metadata) → TaskResult
```

Because the branch lives at the single agent-dispatch seam, hermes agents work in **solo instances, multi-agent labs, and per-agent cron** without strategy changes. Bob Labs tools are deliberately not offered to hermes agents (Hermes brings its own), and tool-call blocks inside Hermes' reply text can never trigger Bob Labs tools.

## The Hermes container

Each hermes-backed **instance** gets its own container and volume — memory is **never shared between instances**. The library agent is the shared *definition* (prompt, model, persona), not a shared brain: two instances of the same template, or the same template dropped into two labs, each keep their own `MEMORY.md`, `USER.md`, skills, `SOUL.md`, and session transcripts.

| Property | Value |
|----------|-------|
| Name | `bob-hermes-<first 12 chars of the instance (lab-agent) id>` |
| Image | `HERMES_IMAGE` (built from [hermes-adapter/](../hermes-adapter/)) |
| Port | 8770 (internal, `HERMES_INTERNAL_PORT`) |
| Network | `bob-network` (same as sandboxes) |
| Memory volume | named volume `bob-hermes-<id>` → `/root/.hermes` — **persistent, per-instance** |
| Resources | `HERMES_MEM_MB` (2048) / `HERMES_CPUS` (2.0) |
| Label | `bob-manager.role=hermes-agent` (orphan cleanup on bob-api startup) |

Lifecycle:

- **Activate** (the instance's UI panel, keyed by its lab-agent id) pops the container and waits for health. Activation is a convenience — any task **lazily ensures** the container, so a Lab run works without pre-activation. The library-agent (template) editor shows a note instead of a panel, since a template has no container of its own.
- **Deactivate** stops the container; **container delete** removes it. Deleting the instance, its lab, or an agent row also stops its container. In every case the `~/.hermes` volume is **kept on purpose**: Hermes' memory, skills, and session transcripts survive, and re-activation restores that instance's brain. (The docker-socket-proxy denies volume-remove APIs anyway — `VOLUMES: 0`.)
- Turns are **serialized per container** (Hermes is a single-loop agent): concurrent tasks queue rather than interleave. Container creation is also lock-protected against concurrent ensure races.
- Stale containers from a previous bob-api run are removed at startup (volumes kept).

> **Migration note:** instances were previously keyed by their *template*, so they shared one volume. After this change each instance keys by its own id and starts from a **fresh, empty** volume on its next run; the old shared `bob-hermes-<template_id>` container is swept at startup (its volume is left behind, never auto-deleted). Previously-accumulated shared memory does not carry into the new isolated volumes.

## The adapter (inside the image)

Vanilla Hermes has no HTTP API (CLI + messaging gateway only). The image built from [hermes-adapter/](../hermes-adapter/) bundles `hermes-agent` (pinned, currently 0.16.0) with a small FastAPI adapter that drives Hermes **in-process** via its library entrypoint (`run_agent.AIAgent` → `run_conversation`). Full wire contract: [hermes-adapter/ADAPTER_CONTRACT.md](../hermes-adapter/ADAPTER_CONTRACT.md).

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | 200 once Hermes is imported and ready |
| `/v1/info` | GET | Hermes + adapter versions |
| `/v1/agent/run` | POST | Run one full task (continuation rounds included), return the final reply |

Build & wire:

```bash
docker build -t bob-hermes-adapter:latest hermes-adapter/
# .env
HERMES_IMAGE=bob-hermes-adapter:latest
# restart bob-api (compose passes HERMES_* through to the container)
```

With `HERMES_IMAGE` unset the feature stays dormant: activation and runs return a clear "Hermes image not configured" error.

### Task-completion protocol (the two-loops problem)

Hermes ends a *turn* whenever its model emits text without tool calls — including mid-work narration ("let me browse the web…"). The Lab loop must only re-engage when the *task* is done, so the adapter runs each task as a continuation loop on one in-memory `AIAgent`:

1. The task is sent with a protocol footer: end with a final line `TASK_DONE` when fully complete, or `NEEDS_INPUT: <question>` when blocked on the operator.
2. A turn that ends with neither marker gets `continue` (same agent, same context) — up to `max_continuations` rounds (default 6).
3. The final reply is returned once: `TASK_DONE` is stripped; a `NEEDS_INPUT` question is kept visible so the operator can answer with a new inject. Markers only count on the trailing lines, so merely *mentioning* the protocol can't end a task.

### Session memory

`run_conversation()` does not accumulate history on its own — the adapter owns the per-session transcript and passes it via `conversation_history` on every call. The transcript lives in memory **and** is mirrored to `/root/.hermes/bob_sessions/<session>.json` on the persistent volume, so conversational continuity survives container restarts. Follow-up tasks ("non, je me suis trompé, c'est vendredi") land with full context of previous tasks. Independently, Hermes uses its own memory/skills tools inside `~/.hermes` for long-term recall.

### Small-context models

Hermes requires a ≥64K context window. Models reporting less (e.g. `qwen2.5:14b` at 32K) trip two Hermes guardrails; the adapter auto-applies Hermes' documented overrides (`model.context_length` + `model.ollama_num_ctx: 65536`) and retries, with a logged warning. Models with native large context (the `qwen3.6` family reports 262K) need no override and are the better choice — see Sizing below.

## Model selection, switching & load balancing

The hermes agent's `model_id` is validated **per task** and Hermes is pointed at the **internal LLM gateway** (`/api/v1/llm-gateway/{agent_id}/v1`, OpenAI-compatible, authenticated with `AGENT_SECRET`). Every model call Hermes makes is then routed by the **LabDispatcher** exactly like a native agent's:

- **load-balanced** across all active providers hosting the `model_identifier` (not pinned to one box), with caller affinity for Ollama KV-cache reuse and failover to the next provider on error;
- subject to the same **per-provider concurrency slots**, so Hermes turns can't collide with native agents on the same Ollama instance;
- **visible in the LLM-event feed** (`caller_type: hermes`, caller name = the agent, queue → dispatch → response events) — Hermes inference shows up in the load-balancer feed like everything else;
- provider formats are handled by the dispatcher's providers (an Anthropic model picked in the dropdown works through the same OpenAI-dialect gateway).

Switching the model in the agent edit form takes effect on the **next task** — no restart, history preserved (the transcript is provider-agnostic).

`HERMES_USE_GATEWAY=false` restores the legacy direct mode (the resolver hands Hermes the provider's own URL — no balancing, no feed events); kept as a debugging escape hatch.

## Operator UI

In the agent edit form (Labs view and Agents tab):

- **Backend** selector (`Native` | `Hermes`) under the model dropdown; for Hermes the dropdown is relabeled "Model Hermes uses".
- The Bob Labs **tools grid and callable-agents are hidden** for hermes agents (Hermes uses its own tools).
- A **Hermes container panel** shows a status dot (running/healthy), with Activate / Deactivate / refresh.

In the Lab transcript, expanding a hermes result message reveals **"⚙ Hermes flow"** — per-round metadata captured from inside Hermes' loop: model calls, tools Hermes used, a reasoning preview, and the `TASK_DONE` / needs-input markers (stored on the message as `extra.hermes_steps`).

## Dispatch paths

| Path | Behavior |
|------|----------|
| Lab runner (`_call_agent`) | Branches to the Hermes executor; native tool loop skipped. Solo instances and multi-agent labs both flow here. |
| Per-agent cron (`lab_scheduler`) | Same branch — a hermes agent with a `cron_expression` delegates the cron instruction to its container. |
| `call_agent` (agent-to-agent) | **Refused with an explicit tool error** — hermes agents own their loop and cannot be driven as nested sub-calls (v1). Address them via orchestrator tasks instead. |

The `backend` field round-trips everywhere agents do: template PATCH cascade to instances, duplicate, instance creation, lab duplicate, lab blueprint export/import, consumer-app `create_agent` / `import_agent` / `AgentOut`, and the agent-template seeder.

## Seeded template

`templates/agent_templates/hermes-real.agent.json` seeds **"Hermes (Nous) — Real Agent"** into the library on startup (`backend: "hermes"`, no tools, no cron). Pick a model, optionally Activate, create an instance or drop it into a Lab.

## API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/library-agents/{id}/hermes/activate` | Yes | Pop/start the container, wait for health |
| POST | `/library-agents/{id}/hermes/deactivate` | Yes | Stop the container (volume kept) |
| DELETE | `/library-agents/{id}/hermes/container` | Yes | Remove the container (volume kept) |
| GET | `/library-agents/{id}/hermes/status` | Yes | `{image_configured, running, healthy, url, backend}` |

The routes accept the **instance (lab-agent) id** — the container is keyed per instance. (A library-agent id still resolves for back-compat, but a template has no container of its own.)

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `HERMES_IMAGE` | `""` (feature off) | Image for the per-agent containers, e.g. `bob-hermes-adapter:latest` |
| `HERMES_DEFAULT_TIMEOUT_SEC` | `1800` | Control-plane wait per task (all continuation rounds included) |
| `HERMES_INTERNAL_PORT` | `8770` | Adapter port inside `bob-network` |
| `HERMES_USE_GATEWAY` | `true` | Route Hermes inference through the internal LLM gateway (dispatcher load balancing + feed). `false` = legacy direct provider calls. |
| `HERMES_GATEWAY_URL` | `http://bob-api:8000` | How Hermes containers reach bob-api on the Docker network |
| `HERMES_MEM_MB` | `2048` | Container memory limit |
| `HERMES_CPUS` | `2.0` | Container CPU limit |

Per-task options understood by the adapter (sent via `options`): `max_iterations` (Hermes loop cap per turn, default 30), `max_continuations` (default 6), `session_id` (default `boblab`).

## Sizing & latency expectations

Every Hermes model call carries Hermes' own system prompt + tool definitions (~10K tokens). Measured on the reference fleet:

| Model | Context | Per call | Typical web-data task |
|-------|---------|----------|------------------------|
| `qwen3.6:27b` (Ollama) | 262K | ~2–3.5 min | ~16 min, 7 calls, 4 tool runs |
| `qwen2.5:14b` (Ollama) | 32K (override applied) | ~1 min | faster but weaker tool use |

Prefer large-context, tool-capable models; MoE variants (`qwen3.6:35b-a3b`) trade well. Hermes turns are expected to be long — that is the point of delegating whole tasks.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Activate returns 409 "image not configured" | Set `HERMES_IMAGE` in `.env` (and ensure compose passes it — it does by default) and restart bob-api. |
| Task error "context window … below the minimum 64,000" persists | The adapter retries with the override automatically; if it still fails the Ollama *runtime* context is capped — pick a larger-context model. |
| Result is `NEEDS_INPUT: …` | Hermes is blocked on a question — answer it with a new inject; session memory carries the context. |
| Old behavior after rebuilding the adapter image | Remove the running `bob-hermes-*` container (`docker rm -f`); the next task recreates it from the new image with the same memory volume. |
| Hermes forgot a conversation after container re-create | Expected only if the **volume** was removed; container removal alone preserves `bob_sessions` + Hermes memory. |

## Related Documents

- [hermes-adapter/ADAPTER_CONTRACT.md](../hermes-adapter/ADAPTER_CONTRACT.md) — full adapter wire contract
- [AGENTS_AND_ORCHESTRATION.md](AGENTS_AND_ORCHESTRATION.md) — agent definition model & execution behavior
- [LABS.md](LABS.md) — loop strategies and lab runtime
- [DISPATCHER_AND_MODEL_ROUTING.md](DISPATCHER_AND_MODEL_ROUTING.md) — model resolution semantics
- [SCHEDULING_AND_CRON.md](SCHEDULING_AND_CRON.md) — per-agent cron path
- [CONFIGURATION.md](CONFIGURATION.md) — environment variable reference
