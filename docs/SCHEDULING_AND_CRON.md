# Bob Labs — Scheduling & Cron

## Overview

Bob Labs supports two scheduling mechanisms that enable autonomous, recurring AI operations:

1. **Lab-level cron** — Triggers a full Lab run on a schedule
2. **Agent-level cron** — Injects a task directly to a specific agent in a running Lab

Both use standard cron expressions parsed by `croniter`. The scheduler runs as a single `asyncio` background task in the control-plane process, polling every 30 seconds.

**Source file:** `control-plane/app/services/lab_scheduler.py`

## Lab-Level Scheduling

### Configuration

Set `cron_expression` on a Lab to trigger automatic runs:

| Field | Type | Description |
|-------|------|-------------|
| `cron_expression` | `VARCHAR(100)` | Cron expression (e.g., `0 9 * * *` for daily at 9 AM) |
| `next_run_at` | `TIMESTAMPTZ` | Computed next trigger time |

### Behavior

```
Scheduler poll (every 30s)
  │
  ├─ SELECT labs WHERE cron_expression IS NOT NULL AND status != 'running'
  │
  ├─ For each lab:
  │   ├─ Compute next_run from cron_expression
  │   ├─ If next_run <= now:
  │   │   ├─ Update next_run_at to the following occurrence
  │   │   ├─ Create LabScheduleLog entry (status: triggered)
  │   │   ├─ Start LabRunner.run() as background task
  │   │   └─ Broadcast lab.cron.triggered via WebSocket
  │   └─ Else: skip (not due)
  │
  └─ Labs currently running are NEVER re-triggered
```

### Schedule Log

Cron triggers are recorded in `lab_schedule_log`:

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | — |
| `lab_id` | UUID FK→labs | Parent Lab |
| `triggered_at` | TIMESTAMPTZ | When the cron fired |
| `completed_at` | TIMESTAMPTZ | When the run finished |
| `status` | VARCHAR(20) | `triggered`, `completed`, `failed` |
| `iterations_run` | INTEGER | Number of iterations in this run |
| `error` | TEXT | Error message if failed |

### Use Cases

- Daily market analysis reports
- Recurring data collection and summarization
- Periodic health checks or monitoring
- Scheduled content generation

## Agent-Level Cron Injection

### Configuration

Each agent can independently define a cron schedule:

| Field | Type | Description |
|-------|------|-------------|
| `cron_expression` | `VARCHAR(100)` | Agent-specific cron schedule |
| `cron_instruction` | TEXT | Instruction to inject when triggered |

### Behavior

Agent crons differ from Lab crons — they inject tasks into **already running or paused Labs** rather than starting new runs:

```
Scheduler poll (every 30s)
  │
  ├─ SELECT lab_agents WHERE cron_expression IS NOT NULL AND is_active
  │
  ├─ For each agent:
  │   ├─ Check parent Lab is running or paused
  │   ├─ Compute previous cron tick
  │   ├─ Check if tick is within POLL_INTERVAL × 2 window
  │   ├─ Deduplicate: check if "[CRON:agent_name]" message already exists for this tick
  │   │
  │   ├─ If not already injected:
  │   │   ├─ Create system message: "[CRON:agent_name] {instruction}"
  │   │   ├─ Broadcast lab.agent.cron.triggered via WebSocket
  │   │   └─ Execute agent task directly (bypasses orchestrator):
  │   │       ├─ Resolve agent tools
  │   │       ├─ Build agent messages with memories + resources
  │   │       ├─ Call agent LLM via dispatcher
  │   │       ├─ Run tool call loop (up to tool_max_calls)
  │   │       └─ Store final result message
  │   └─ Skip if already injected (deduplication)
```

### Deduplication

The scheduler prevents duplicate injections by checking recent messages for the `[CRON:agent_name]` prefix within a 10-second window around the cron tick. This handles overlapping poll windows gracefully.

### Direct Execution

Agent cron tasks execute **directly** — the agent receives its instruction and runs a full tool loop without going through the orchestrator. This is efficient for recurring tasks where the orchestrator doesn't need to plan.

### Use Cases

- Agent "Researcher" checks news every hour: `0 * * * *`
- Agent "Monitor" fetches metrics every 15 minutes: `*/15 * * * *`
- Agent "Summarizer" compiles daily digest at midnight: `0 0 * * *`

## CronJob Model

The platform also supports standalone cron jobs (not tied to Labs):

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | — |
| `name` | VARCHAR(255) UNIQUE | Job name |
| `description` | TEXT | — |
| `cron_expression` | VARCHAR(100) | Schedule |
| `job_type` | VARCHAR(50) | Job type identifier |
| `job_config` | JSONB | Job-specific configuration |
| `is_active` | BOOLEAN | Enable/disable |
| `last_run_at` | TIMESTAMPTZ | Last execution time |
| `next_run_at` | TIMESTAMPTZ | Next scheduled time |
| `created_at` | TIMESTAMPTZ | — |

## Lifecycle

The scheduler is managed via application startup/shutdown hooks in `main.py`:

```python
@app.on_event("startup")
async def start_scheduler():
    start_lab_scheduler(async_session_factory)

@app.on_event("shutdown")
async def stop_scheduler():
    stop_lab_scheduler()
```

## Cron Expression Reference

Standard 5-field cron syntax:

```
┌───────── minute (0-59)
│ ┌─────── hour (0-23)
│ │ ┌───── day of month (1-31)
│ │ │ ┌─── month (1-12)
│ │ │ │ ┌─ day of week (0-6, Sun=0)
│ │ │ │ │
* * * * *
```

| Expression | Meaning |
|------------|---------|
| `0 9 * * *` | Daily at 9:00 AM |
| `*/15 * * * *` | Every 15 minutes |
| `0 */6 * * *` | Every 6 hours |
| `0 0 * * 1` | Every Monday at midnight |
| `30 8 1 * *` | 1st of each month at 8:30 AM |

## Related Documents

- [LABS.md](LABS.md) — Lab runtime and agent execution
- [AGENTS_AND_ORCHESTRATION.md](AGENTS_AND_ORCHESTRATION.md) — Orchestration model
- [CONFIGURATION.md](CONFIGURATION.md) — Environment variables