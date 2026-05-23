# Anti-Loop

> **Status:** ✅ Implemented (control-plane + frontend, opt-in per lab/agent)
> **Module:** `app.services.loop_detection`
> **Migration:** `026_anti_loop.sql`

---

## 1. What it does

The Anti-Loop subsystem watches every message produced by an orchestrator
or an agent inside a running lab and detects when the lab is **stuck in a
repetitive pattern** (semantic loop or repeated tool call). When a loop
is detected and the feature is enabled, the lab is automatically:

1. **paused** — the runner stops scheduling the next iteration,
2. **healed** — the looping messages are removed from the lab history,
3. **resumed** — the runner picks up from a clean state.

The user is notified through WebSocket events and the recovery is
recorded in a dedicated audit table.

> Loops are detected **in the background**. The lab loop never blocks
> on embedding or detection. If the embedder is slow, iterations
> continue normally.

---

## 2. Architecture

```
                ┌─────────────────────────┐
                │   LabRunner (asyncio)   │
                │                         │
                │   iter N → save msg ────┼─► msg_repo.create()
                │                         │        │
                │                         │        ▼
                │                         │   observe_message()  ◄── synchronous, ~µs
                │                         │        │
                │                         │        ├─► append to per-actor deque
                │                         │        │
                │                         │        ├─► quick check (tool_repeat) — synchronous
                │                         │        │
                │                         │        └─► asyncio.create_task(_embed_and_check(...))
                │                         │                                  │
                │   iter N+1 ─────────────┘                                  │
                │   (continues immediately, never blocked)                   │
                └────────────────────────────────────────────────────────────┘
                                                                             │
                                                                             ▼
                                                          ┌──────────────────────────────────┐
                                                          │  Background task                 │
                                                          │  1. EmbeddingService.embed_query │
                                                          │  2. CompositeDetector.check()    │
                                                          │  3. broadcast `lab.loop_warning` │
                                                          │  4. if RED & enabled → recover() │
                                                          └──────────────────────────────────┘
                                                                             │
                                                                             ▼
                                                          ┌──────────────────────────────────┐
                                                          │  recover():                      │
                                                          │   runner.pause()                 │
                                                          │   DELETE looping rows            │
                                                          │   drop from in-memory buffer     │
                                                          │   INSERT lab_loop_events         │
                                                          │   broadcast `lab.loop_recovered` │
                                                          │   runner.resume()                │
                                                          └──────────────────────────────────┘
```

Key property: `observe_message()` is **synchronous and never awaits the
embedder**. Embedding happens in a fire-and-forget `asyncio.create_task`,
so a slow embedding model (or transient embedding failure) cannot stall
the lab.

---

## 3. Detectors

The default composite runs the cheapest detector first, then the
semantic one, and returns the worst severity.

### 3.1 `ToolRepeatDetector`

Hashes each tool invocation as `sha256({"name", "args"})` (sorted JSON).
If the same hash appears **≥ 3 times** in the recent history of a single
actor, it triggers.

| Repeats | Severity | Score |
|---------|----------|-------|
| 3       | yellow   | 60    |
| 4       | orange   | 80    |
| ≥ 5     | red      | 100   |

### 3.2 `SemanticLoopDetector`

Computes pairwise cosine similarity over the last 5 *embedded* messages
of the actor. Embeddings come from `EmbeddingService.embed_query()`
(sentence-transformers, already L2-normalized, so cosine == dot product).

| Pairs ≥ 0.90 cosine | Severity | Score |
|---------------------|----------|-------|
| 1 (warning)         | yellow   | 60    |
| 2                   | orange   | 80    |
| ≥ 3                 | red      | 100   |

### 3.3 `CompositeDetector`

Returns `LoopReport(detected, severity, score, signals[], loop_message_ids[])`
combining all detectors. `severity == "red"` is the only level that
triggers automatic recovery; lower levels are informational.

---

## 4. Recovery flow

Triggered only when **both** conditions are met:

* `severity == "red"`
* `lab.anti_loop_enabled` (or the agent's `anti_loop_enabled`) is `true`

Steps performed by `LoopManager._recover()`:

1. **Pause.** `runner.pause()` — the next `await self._iter_gate.wait()`
   in the runner blocks until resume is called.
2. **Purge memory.** A single SQL statement removes the looping rows
   identified by the detector:
   ```sql
   DELETE FROM lab_messages
    WHERE lab_id = :lab_id
      AND id = ANY(:ids)
   ```
3. **Drop from in-memory buffers** so the same messages are not detected
   again on the next observation.
4. **Audit.** Insert into `lab_loop_events` (severity, score, signals,
   removed message ids, count, timestamp).
5. **Notify clients.** Broadcast `lab.loop_recovered` over the WebSocket
   hub.
6. **Resume.** `runner.resume()` — iterations continue.

A per-lab `_recovering: set[UUID]` lock prevents concurrent recoveries
on the same lab.

---

## 5. Database schema

### Columns added to existing tables (migration `026`)

```sql
ALTER TABLE labs            ADD COLUMN anti_loop_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE lab_agents      ADD COLUMN anti_loop_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE library_agents  ADD COLUMN anti_loop_enabled BOOLEAN NOT NULL DEFAULT false;
```

### `lab_loop_events`

```sql
CREATE TABLE lab_loop_events (
    id                   UUID PRIMARY KEY,
    lab_id               UUID NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    severity             TEXT NOT NULL,
    score                INTEGER NOT NULL,
    signals              JSONB NOT NULL,
    removed_message_ids  JSONB NOT NULL,
    removed_count        INTEGER NOT NULL,
    recovered            BOOLEAN NOT NULL DEFAULT false,
    detected_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_lab_loop_events_lab ON lab_loop_events(lab_id, detected_at DESC);
```

The migration is applied automatically by the `ensure_anti_loop_schema`
startup hook in `control-plane/app/main.py`.

---

## 6. WebSocket events

Both events carry `lab_id` and are scoped per lab.

### `lab.loop_warning`

Emitted on **any** detection (yellow / orange / red), regardless of
whether anti-loop is enabled. Used to surface diagnostic info in the UI.

```json
{
  "type": "lab.loop_warning",
  "payload": {
    "lab_id": "…",
    "severity": "orange",
    "score": 80,
    "signals": [
      { "name": "semantic_loop",  "score": 80, "detail": {"pairs": 2} },
      { "name": "tool_repeat",    "score": 60, "detail": {"hash": "…", "count": 3} }
    ],
    "loop_message_ids": ["…", "…"]
  }
}
```

### `lab.loop_recovered`

Emitted **after** a successful red-level recovery.

```json
{
  "type": "lab.loop_recovered",
  "payload": {
    "lab_id": "…",
    "severity": "red",
    "score": 100,
    "removed_count": 4,
    "removed_message_ids": ["…", "…", "…", "…"]
  }
}
```

---

## 7. REST API

| Method | Path                                      | Purpose                              |
|--------|-------------------------------------------|--------------------------------------|
| GET    | `/api/v1/labs/{lab_id}/loop-events`       | History of detections (audit log).   |
| GET    | `/api/v1/labs/{lab_id}/loop-status`       | In-memory buffer sizes per actor.    |

`loop-events` accepts `?limit=N` (default 50, max 200). Rows are
ordered `detected_at DESC`.

---

## 8. Configuration

All knobs are constants on `LoopManager` (`manager.py`):

| Constant              | Default | Meaning                                                   |
|-----------------------|---------|-----------------------------------------------------------|
| `WINDOW_SECONDS`      | 600     | Sliding window per actor (older entries dropped).         |
| `HISTORY_PER_ACTOR`   | 12      | `deque(maxlen=…)` for buffered messages per actor.        |
| `MIN_CONTENT_LEN`     | 20      | Skip embedding for very short messages.                   |
| `RED_AUTOACT_SEVERITY`| `"red"` | Severity threshold that triggers automatic recovery.      |

Detector thresholds live on the detector classes and can be changed in
`detectors.py`:

* `SemanticLoopDetector(threshold=0.90, trigger_count=3, history_size=5)`
* `ToolRepeatDetector(trigger_count=3, history_size=5)`

---

## 9. UX

### Lab settings panel

A new **Anti Loop** checkbox sits next to **Auto Sweep Memory**. Enabling
it shows a `window.confirm` warning:

> When a loop is detected, the lab will be paused, the looping messages
> will be removed from memory, and the lab will resume.
> The agent may lose information about its recent reasoning, and in some
> cases this can cause unexpected behavior. Continue?

Per-agent toggles (`LabAgent.anti_loop_enabled`,
`LibraryAgent.anti_loop_enabled`) are exposed in the agent edit forms.
Either the lab-level or the agent-level flag is sufficient to enable
recovery for that actor.

### Toasts

Both WS events are forwarded to a `bob:toast` `CustomEvent` that any
toast layer can listen to:

* `lab.loop_warning` → `warning` toast: `Loop ORANGE: semantic_loop, tool_repeat (score 80)`
* `lab.loop_recovered` → `info` toast: `Anti-loop: removed 4 looping message(s) and resumed`

---

## 10. Coverage

Current observation hooks call `LoopManager.observe_message()` from
`lab_runner.py` at three points:

| Site                           | `actor_key`         |
|--------------------------------|---------------------|
| Orchestrator decision message  | `orchestrator`      |
| Agent intermediate `message`   | `agent:<name>`      |
| Agent `result` message         | `agent:<name>`      |

Tool-result messages are **not** observed (tool outputs are large,
typically distinct, and not the source of true loops). Tool repetition
itself is captured because tool calls are fingerprinted in the agent
message that emits them.

When a runner stops, `LoopManager.reset_lab(lab_id)` clears all buffers
for that lab.

---

## 11. Limitations & future work

* **Embedding model required.** If `EmbeddingService.embed_query()`
  fails repeatedly, the semantic detector silently degrades to
  tool-repeat-only detection.
* **No cross-actor detection.** The current detector compares messages
  *within* an actor's stream. Cross-actor ping-pong loops (e.g. two
  agents echoing each other) are not yet detected.
* **Hard-coded thresholds.** Per-lab tuning is not yet exposed in the
  UI; thresholds are global module constants.
* **Resume semantics.** After purging, the orchestrator resumes from its
  last decision point. If the loop was caused by an external condition
  (e.g. a tool that always returns the same data), the lab may re-enter
  the same loop and trigger a second recovery.
