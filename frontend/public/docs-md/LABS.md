# Bob Labs — Labs Architecture

## 1. What is a Lab?

A **Lab** is a persistent multi-agent workspace where a central **Orchestrator** coordinates N specialized **Agents** to accomplish complex tasks autonomously.

```
User  ──message──►  Orchestrator  ──sub-tasks──►  Agent Researcher   (web, databases)
      ◄──result───               ◄──returns────   Agent Analyst      (code, charts)
                                                   Agent Writer       (writing, formatting)
                                                   Agent Designer     (images, diagrams)
                                                   ...
```

Key properties:

| Property | Description |
|----------|-------------|
| **Persistent** | A Lab survives across sessions. It can run for days, be paused, and resumed. All work is preserved. |
| **Multi-agent** | 1 Orchestrator + N Agents, each with its own model, system prompt, tools, and memory. |
| **Auto-pilot** | The agent loop runs autonomously. User watches in real-time via WebSocket. |
| **Pausable** | User can pause at any point, edit context (prompts, tools, models), then resume. |
| **Limitable** | Max iterations and max duration limits. When reached → auto-complete. |
| **Model-swappable** | Change any agent's or orchestrator's model at any time without losing work. |
| **Scheduled** | Labs can be triggered on a cron schedule. Agents can also have individual cron schedules to inject tasks. |
| **Cross-callable** | Agents can directly call other agents in the same lab via the `call_agent` tool, bypassing the orchestrator. |
| **Tool Sets** | Reusable tool presets that can be assigned to agents or the orchestrator. |

---

## 2. Core Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND (React)                                  │
│                                                                             │
│  Lab Central View:                                                          │
│  ┌────────────┐  ┌───────────────────────────────┐  ┌───────────────────┐  │
│  │ Lab List   │  │   Execution Timeline           │  │  Agent Inspector  │  │
│  │ + Tool Sets│  │   (messages + tasks + actions)  │  │  - Agents         │  │
│  │            │  │                                 │  │  - Resources      │  │
│  │ • Lab A 🟢│  │   [ORCH] Analyzing request...   │  │  - Output Files   │  │
│  │ • Lab B ⏸ │  │   [ORCH→Researcher] Find data   │  │  - Memory         │  │
│  │ • Lab C 🔴│  │   [Researcher] Searching web...  │  │  - Config         │  │
│  │            │  │   [Researcher→ORCH] Found 12 ..  │  │                   │  │
│  │ + New Lab  │  │   [ORCH→Analyst] Analyze ...     │  │                   │  │
│  │            │  │   [Analyst] Processing...        │  │                   │  │
│  │            │  │                                 │  │                   │  │
│  │            │  │  ┌──────────────────────────┐   │  │                   │  │
│  │            │  │  │ 💬 User input / Inject   │   │  │                   │  │
│  │            │  │  └──────────────────────────┘   │  │                   │  │
│  └────────────┘  └───────────────────────────────┘  └───────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                             │
                             │ REST + WebSocket
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CONTROL PLANE (FastAPI)                              │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    Lab Engine                                         │  │
│  │                                                                       │  │
│  │  ┌──────────────┐  ┌───────────────┐  ┌────────────────────────────┐ │  │
│  │  │  Lab Runner   │  │  Loop         │  │  Dispatcher / Balancer     │ │  │
│  │  │              │  │  Strategies   │  │                            │ │  │
│  │  │ • run()      │  │              │  │  • _find_all_providers()   │ │  │
│  │  │ • pause()    │  │  • plan_exec │  │  • _call_with_loadbalance()│ │  │
│  │  │ • resume()   │  │  • critique  │  │  • call_orchestrator()     │ │  │
│  │  │ • inject()   │  │  • round_rob │  │  • call_agent()            │ │  │
│  │  │ • stop()     │  │              │  │                            │ │  │
│  │  └──────┬───────┘  └───────┬───────┘  └───────────┬────────────────┘ │  │
│  │         │                  │                       │                  │  │
│  │  ┌──────┴──┐  ┌────────────┴──┐  ┌────────────────┴───────────────┐ │  │
│  │  │ Tool    │  │  Lab          │  │  LLM Provider Layer            │ │  │
│  │  │Executor │  │  Scheduler    │  │  OllamaProvider · vLLMProvider │ │  │
│  │  │(18 tool │  │  (cron jobs)  │  │  OpenAIProvider · HFProvider   │ │  │
│  │  └────┬────┘  └───────────────┘  └────────────────────────────────┘ │  │
│  │       │ HTTP                                                         │  │
│  │       ▼                                                              │  │
│  │  ┌──────────────────────────────────────────────┐                    │  │
│  │  │  Container Manager (Docker SDK)               │                   │  │
│  │  │  Per-lab sandbox containers (bob-lab-{id})    │                   │  │
│  │  │  Create on Run · Destroy on Delete/Reset      │                   │  │
│  │  │  Stop on Complete · Lazy-create on tool use   │                   │  │
│  │  └──────────────────────────────────────────────┘                    │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                   Shared Infrastructure                               │  │
│  │  PostgreSQL (labs, agents, messages, memory, tools, resources)         │  │
│  │  WebSocket Hub (real-time UI updates)                                 │  │
│  │  Lab Scheduler (cron-based recurring labs + agent-level cron)         │  │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
           │                      │                      │
           │ Docker API           │                      │
           ▼                      │                      │
┌──────────────────┐              │                      │
│  bob-lab-{id}    │       ┌──────┴──────┐        ┌──────┴──────┐
│  Per-lab sandbox │       │  GPU Server  │        │  Cloud API   │
│  (python_exec,   │       │   Ollama     │        │   OpenAI     │
│   shell_exec)    │       │   vLLM       │        │   etc.       │
│  Isolated Docker │       └──────────────┘        └──────────────┘
│  container       │
└──────────────────┘
```

---

## 3. Data Model

### 3.1 Entity Overview

| Table | Purpose |
|-------|---------|
| `labs` | Lab workspace: config, status, orchestrator settings, limits, scheduling |
| `lab_agents` | Agent definitions: model, prompt, tools, callable agents, cron schedule |
| `lab_tools` | Custom tool definitions per lab |
| `lab_messages` | Unified execution log / conversation (all message types) |
| `lab_memories` | Persistent key-value memory per lab or per agent |
| `lab_resources` | Uploaded files (code, images, PDFs) for agent context |
| `lab_schedule_log` | Tracks cron-triggered runs |
| `tool_sets` | Reusable tool presets (shared across labs) |
| `llm_events` | Load-balancer activity log (queue/dispatch/response/failed) |

### 3.2 Labs Table

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | UUID PK | auto | |
| `name` | VARCHAR(255) | — | Lab name |
| `description` | TEXT | `""` | |
| `status` | VARCHAR(20) | `"created"` | created / running / paused / completed / failed |
| `loop_type` | VARCHAR(50) | `"plan_execute"` | plan_execute / critique_refine / round_robin |
| `loop_config` | JSONB | `{}` | Strategy-specific parameters |
| `orchestrator_model_id` | UUID FK→ai_models | NULL | Orchestrator's LLM model |
| `orchestrator_prompt` | TEXT | `""` | Custom orchestrator instructions |
| `orchestrator_temperature` | NUMERIC(3,2) | `0.70` | |
| `orchestrator_max_tokens` | INTEGER | `4096` | |
| `orchestrator_tools` | JSONB | `[]` | Tools assigned to orchestrator |
| `orchestrator_tool_set_id` | UUID FK→tool_sets | NULL | Tool set for orchestrator |
| `max_iterations` | INTEGER | NULL | Max loop iterations (NULL = unlimited) |
| `max_duration_sec` | INTEGER | NULL | Max wall-clock seconds (NULL = unlimited) |
| `current_iteration` | INTEGER | `0` | Current iteration counter |
| `cron_expression` | VARCHAR(100) | NULL | Cron schedule for automatic runs |
| `next_run_at` | TIMESTAMPTZ | NULL | Next scheduled run time |
| `context_files` | JSONB | `[]` | Inline context documents |
| `share_memory_override` | BOOLEAN | NULL | Override agent share_memory setting |
| `tool_max_calls` | INTEGER | `10` | Max tool calls per agent per turn |
| `tool_timeout_sec` | INTEGER | `30` | Tool execution timeout |
| `tool_max_output_kb` | INTEGER | `256` | Max tool output size |
| `tool_container_memory_mb` | INTEGER | `512` | Container memory limit for tools |
| `started_at` | TIMESTAMPTZ | NULL | |
| `paused_at` | TIMESTAMPTZ | NULL | |
| `completed_at` | TIMESTAMPTZ | NULL | |
| `created_at` | TIMESTAMPTZ | `now()` | |
| `updated_at` | TIMESTAMPTZ | `now()` | |

### 3.3 Lab Agents Table

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | UUID PK | auto | |
| `lab_id` | UUID FK→labs | — | Parent lab (CASCADE delete) |
| `name` | VARCHAR(255) | — | Unique per lab |
| `role` | TEXT | `""` | Short role description |
| `system_prompt` | TEXT | `""` | Agent's system prompt |
| `model_id` | UUID FK→ai_models | NULL | Agent's LLM model |
| `temperature` | NUMERIC(3,2) | `0.70` | |
| `max_tokens` | INTEGER | `4096` | |
| `tools` | JSONB | `[]` | Manually selected tool names |
| `tool_set_id` | UUID FK→tool_sets | NULL | Tool set assignment |
| `is_active` | BOOLEAN | `TRUE` | |
| `sort_order` | INTEGER | `0` | |
| `share_memory` | BOOLEAN | `FALSE` | Access memories from all labs |
| `callable_agents` | JSONB | `[]` | List of agent names this agent can call |
| `cron_expression` | VARCHAR(100) | NULL | Cron schedule for task injection |
| `cron_instruction` | TEXT | `""` | Instruction to inject on cron trigger |
| `created_at` | TIMESTAMPTZ | `now()` | |
| `updated_at` | TIMESTAMPTZ | `now()` | |

### 3.4 Other Tables

**lab_tools** — Custom tool definitions per lab (name, description, tool_type, config, execution_side, is_enabled).

**lab_messages** — Unified log with columns: `iteration`, `sender_type` (user/orchestrator/agent/system), `sender_agent_id`, `sender_name`, `target_agent_id`, `target_name`, `content`, `message_type` (message/task/result/error/tool_call/tool_result/inject/summary/file_event), `model_used`, `provider_used`, `tokens_in`, `tokens_out`, `duration_ms`, `tool_name`, `tool_input`, `tool_output`, `extra`.

**lab_memories** — Persistent memory: `agent_id` (NULL = lab-wide), `scope` (lab/agent), `key`, `content`, `memory_type` (fact/insight/preference/learning/error_pattern/tool), `importance` (1-10), `expires_at`.

**lab_resources** — Uploaded files: `filename`, `original_name`, `content_type`, `size_bytes`, `resource_type` (file/image/pdf/code), `description`.

**lab_schedule_log** — Cron run log: `lab_id`, `triggered_at`, `completed_at`, `status`, `iterations_run`, `error`.

**tool_sets** — Reusable presets: `name` (unique), `description`, `tools` (JSONB list of tool names).

**llm_events** — Load balancer log: `request_id`, `event_type` (queue/dispatch/response/failed), `model_identifier`, `provider_name`, `server_name`, `caller_type` (lab_orchestrator/lab_agent/conversation), `caller_name`, `lab_id`, `conversation_id`, `tokens_in`, `tokens_out`, `duration_ms`, `attempt`, `max_attempts`, `error`.

---

## 4. The Agent Loop (Pluggable Strategy)

The agent loop is the heart of the Lab. It is **abstracted as a pluggable strategy** so users can swap loop types without changing the rest of the system.

### 4.1 Loop Strategy Abstraction

```python
class LoopStrategy(ABC):
    @abstractmethod
    async def initialize(self, lab: Lab, agents: list[LabAgent]) -> None:
        """Called once when the lab starts or resumes."""

    @abstractmethod
    async def next_step(self, context: LoopContext) -> LoopAction:
        """Given current context, decide what to do next.
        Returns PlanAction, SynthesizeAction, PauseAction, or _PendingLLMCall."""

    @abstractmethod
    async def on_results(self, context: LoopContext, results: list[TaskResult]) -> None:
        """Called when agent results come back."""

    @abstractmethod
    async def on_inject(self, context: LoopContext, message: str) -> None:
        """Called when user injects a message."""

@dataclass
class LoopContext:
    lab: Lab
    agents: list[LabAgent]
    iteration: int
    elapsed_sec: float
    messages: list[LabMessage]
    lab_memories: list[LabMemory]
    user_injections: list[str]
    resources: list[LabResource]
```

### 4.2 Built-in Strategies

| Strategy | `loop_type` | Description |
|----------|-------------|-------------|
| **Plan & Execute** | `plan_execute` | Default. Orchestrator decomposes → agents execute → collect → decide. |
| **Critique & Refine** | `critique_refine` | Alternates create / critique / refine phases until quality threshold. |
| **Round Robin** | `round_robin` | Each agent speaks in turn. Accumulates all results across rounds. |

```python
# services/loop_strategies/__init__.py
STRATEGY_REGISTRY = {
    "plan_execute": PlanExecuteStrategy,
    "critique_refine": CritiqueRefineStrategy,
    "round_robin": RoundRobinStrategy,
}

def get_strategy(loop_type: str, loop_config: dict) -> LoopStrategy:
    cls = STRATEGY_REGISTRY.get(loop_type)
    if cls is None:
        raise ValueError(f"Unknown loop strategy: {loop_type}")
    return cls(**loop_config)
```

### 4.3 Lab Runner Main Loop (`_run_loop`)

```
LabRunner._run_loop()
    │
    ├─ Open DB session, load lab + active agents
    ├─ strategy = get_strategy(lab.loop_type, lab.loop_config)
    ├─ Create LabDispatcher (load-balanced LLM calls)
    ├─ Resolve orchestrator tools (manual or via tool set)
    ├─ Build native tool schema if orchestrator has tools
    ├─ Set status="running", broadcast lab.started
    │
    └─ while True:
        ├─ Check _stop_requested → complete (reason: stopped)
        ├─ await _paused.wait() → blocks if paused
        ├─ Check max_iterations → complete (reason: max_iterations)
        ├─ Check max_duration_sec → complete (reason: max_duration)
        │
        ├─ Build LoopContext (recent 50 messages, memories, injections, resources)
        ├─ action = strategy.next_step(context)
        │
        ├─ If _PendingLLMCall:
        │     ├─ Call orchestrator LLM via dispatcher
        │     ├─ Store orchestrator message, broadcast
        │     │
        │     ├─ If orchestrator has tools → TOOL CALL LOOP:
        │     │     ├─ Check native tool_calls first
        │     │     ├─ Fallback: parse_tool_calls() from text
        │     │     ├─ Execute tools, store messages
        │     │     ├─ Re-call orchestrator with results
        │     │     └─ Repeat up to tool_max_calls
        │     │
        │     └─ parse_orchestrator_response() → PlanAction / SynthesizeAction / PauseAction
        │        (with safety: blocks done=true on iteration 0, retries on bad JSON)
        │
        ├─ If PlanAction:
        │     ├─ _execute_tasks() → run all agents concurrently
        │     └─ strategy.on_results()
        │
        ├─ If SynthesizeAction:
        │     ├─ Store synthesis, save as memory (importance=8)
        │     └─ Set status="completed", broadcast lab.completed
        │
        ├─ If PauseAction:
        │     ├─ Set status="paused", broadcast lab.paused
        │     └─ Block on _paused.wait()
        │
        └─ Increment iteration, broadcast lab.iteration
```

### 4.4 Agent Execution (`_execute_tasks`)

When the orchestrator produces a `PlanAction` with tasks:

1. Map task agent names to `LabAgent` objects
2. Store task assignment messages (`message_type="task"`)
3. Run ALL agents **concurrently** via `asyncio.gather()`
4. Per agent:
   - Load memories (shared across all labs if `share_memory`, else lab-only)
   - Load resources, resolve tools (manual or tool set)
   - Build agent messages (`_build_agent_messages`)
   - Call LLM via `dispatcher.call_agent()`
   - **Hybrid tool call loop**:
     - Try native `tool_calls` from LLM response first
     - Fallback: `parse_tool_calls()` from response text
     - Validate tool is assigned to agent
     - Execute via `ToolExecutor`
     - Send results back (native format or `<tool_result>` text)
     - Re-call agent with updated context
     - Repeat up to `lab.tool_max_calls` per turn
   - Extract & save base64 images from response → `LabResource` records
   - Store final result message, broadcast `lab.task.complete`

### 4.5 Hybrid Tool Calling

The system supports two tool-calling modes simultaneously:

**Native mode** — For models with function-calling support (Qwen2.5, Llama3.1, etc.). Tools are described via the OpenAI `tools` schema. The LLM returns structured `tool_calls` in the response. Results are sent back as `role: "tool"` messages.

**Text mode** — For models without native support. Tools are described in the system prompt. The LLM writes `<tool_call>{"name": ..., "arguments": ...}</tool_call>` in its response text. Results are injected as `<tool_result>` blocks in a `role: "user"` message.

The runner tries native first, then falls back to text parsing. This means models can mix both modes transparently — `build_native_tools_schema()` generates the OpenAI schema, while `format_tool_descriptions()` generates the text-based prompt injection.

### 4.6 Orchestrator Plan Format (Plan & Execute)

The orchestrator must respond with valid JSON:

```json
{
  "reasoning": "The user wants a market analysis. I need data, analysis, and a report.",
  "tasks": [
    {
      "agent": "Researcher",
      "instruction": "Find the latest market data for electric vehicles in Europe.",
      "depends_on": []
    },
    {
      "agent": "Analyst",
      "instruction": "Analyze the data found by Researcher. Produce charts.",
      "depends_on": ["Researcher"]
    }
  ],
  "done": false,
  "summary": null
}
```

Safety rules enforced by `parse_orchestrator_response()`:
- `done: true` is blocked on the first iteration (must execute at least one task)
- `done: true` is blocked when no results have been received yet
- `done: true` without tasks is blocked when there's a pending user injection
- Bad JSON triggers a retry with a correction message

### 4.7 State Machine

```
                    ┌──────────┐
                    │ created  │
                    └────┬─────┘
                         │  user clicks "Run" or cron triggers
                         ▼
                    ┌──────────┐
         ┌─────────│ running   │◄─────────┐
         │         └────┬─────┘          │
         │              │                 │  user clicks "Resume"
         │   limit hit  │  user clicks    │
         │   or orch    │  "Pause"        │
         │   PauseAction▼                 │
         │         ┌──────────┐           │
         │         │ paused   │───────────┘
         │         └────┬─────┘
         │              │  user clicks "Stop"
         │              ▼
         │         ┌──────────┐
         │         │ completed│  (also: max_iterations, max_duration, done)
         │         └──────────┘
         │
         │  unrecoverable error
         ▼
    ┌──────────┐
    │  failed  │
    └──────────┘
```

---

## 5. Tools System

### 5.1 Builtin Tools

> The platform includes **34 builtin tools**. For the complete tool reference with descriptions and parameters, see [TOOLS_AND_SANDBOX.md](TOOLS_AND_SANDBOX.md).
>
> The list below shows the original 18 tools documented at the time of writing. Additional tools added since then include: `rag_list_collections`, `rag_search`, `rag_ingest`, `audio_generate`, `media_pipeline`, `audio_mix`, `youtube`, `mail`, `video_generate`, `twitter`, and others.

| # | Tool | Description | Parameters |
|---|------|-------------|------------|
| 1 | `think` | Private reasoning step (not shown to others) | `thought: string` |
| 2 | `memory_save` | Save a fact to lab memory | `key: string`, `content: string`, `importance: integer` (opt, 1-10, default 5) |
| 3 | `memory_search` | Search lab memories by keyword | `query: string` |
| 4 | `file_read` | Read a file from the lab workspace | `path: string` |
| 5 | `file_write` | Write content to `output/` directory | `path: string`, `content: string` |
| 6 | `python_exec` | Execute Python code in per-lab sandbox container | `code: string` |
| 7 | `shell_exec` | Execute whitelisted shell commands in per-lab sandbox | `command: string` |
| 8 | `image_generate` | Generate images via external API | `prompt: string`, `width: integer` (opt, 1024), `height: integer` (opt, 1024) |
| 9 | `web_search` | Search the web via DuckDuckGo | `query: string`, `max_results: integer` (opt, 5, max 10) |
| 10 | `web_extract` | Fetch URL and extract text content | `url: string` |
| 11 | `browser_navigate` | Open URL in headless Chromium (Playwright) | `url: string` |
| 12 | `browser_snapshot` | Text snapshot of current browser page | *(none)* |
| 13 | `mermaid_to_img` | Convert Mermaid diagram to SVG/PNG/PDF via Docker | `input_path: string`, `output_format: string` (opt, "svg") |
| 14 | `call_agent` | Call another agent directly (bypasses orchestrator) | `agent_name: string`, `instruction: string` |
| 15 | `handle_memory` | Manage agent memories (list/hide/show) | `agent_name: string`, `action: string` (list/hide/show), `memory_ids: string` (opt) |
| 16 | `excalidraw` | Create Excalidraw diagrams, render to PNG, upload for sharing | `elements: string` (JSON), `filename: string` (opt), `dark_mode: string` (opt) |
| 17 | `blockchain` | Query on-chain data (Ethereum, Base, Solana) | `action: string` (balance/transactions/token_transfers/token_info), `address: string`, `chain: string` (opt), `limit: integer` (opt) |
| 18 | `clock` | Time tracking (start/stop/elapsed/reset/timestamp/list timers) | `action: string`, `name: string` (opt) |

### 5.2 Tool Execution Details

**`think`** — Records the thought, returns confirmation. Used for chain-of-thought reasoning.

**`memory_save`** — Creates `LabMemory` with `scope="lab"`, `memory_type="tool"`. Importance clamped 1-10, content capped at 5000 chars.

**`memory_search`** — Fetches 50 memories for the lab, case-insensitive keyword match on key + content, returns top 10.

**`file_read`** — Resolves path within workspace (tries workspace root, then `output/`). Path traversal is blocked.

**`file_write`** — Writes only to `output/` subdirectory. Creates parent directories. Returns a `file_event` with action `"created"` or `"edited"`.

**`python_exec`** — Writes code to temp file, runs `python3` subprocess in the lab's isolated Docker sandbox container. Each lab has its own `bob-lab-{id}` container.

**`shell_exec`** — Validates first token against whitelist: `curl, wget, python3, python, pip, pip3, cat, head, tail, wc, grep, awk, sed, sort, uniq, ls, find, echo, date, whoami, uname, jq, bc, tr, cut, tee, xargs, freecadcmd, freecad, kicad-cli`. Runs in per-lab sandbox container.

**`image_generate`** — POSTs to `IMAGE_GEN_API_URL/v1/images/generations` with `response_format: "b64_json"`, saves PNG to `output/generated_images/`, returns `file_event`.

**`web_search`** — Uses `duckduckgo_search.DDGS` library. Runs in thread executor. Results capped at 10.

**`web_extract`** — Fetches URL with httpx. SSRF protection (blocks private IP ranges). BeautifulSoup text extraction, strips scripts/styles.

**`browser_navigate`** — Playwright headless Chromium. SSRF protection. Waits for `domcontentloaded`, removes nav/footer/header/script elements, returns page text.

**`browser_snapshot`** — Returns current page's `innerText` (requires prior `browser_navigate`).

**`mermaid_to_img`** — Runs `docker run minlag/mermaid-cli` with workspace volume mount. Handles single `.mmd` files and `.md` files containing multiple mermaid code blocks (extracts each block, produces numbered output files).

**`call_agent`** — Delegates to a callback created by `LabRunner._make_call_agent_handler()`. The caller must have the target listed in `callable_agents`. The target agent runs a full tool loop but **cannot use `call_agent` itself** (prevents infinite recursion).

**`handle_memory`** — Orchestrator-only tool for managing agent memories. List all memories for an agent (including hidden status), hide memories to exclude from prompts, or show hidden memories to re-include them.

**`excalidraw`** — Creates an Excalidraw diagram from JSON elements, saves as `.excalidraw` file, renders to PNG via headless Chromium, and uploads to excalidraw.com for a shareable link.

**`blockchain`** — Queries on-chain blockchain data via Blockscout and public RPCs. Supports Ethereum, Base, and Solana. Actions: `balance` (native + token), `transactions`, `token_transfers`, `token_info`.

**`clock`** — Manages named timers for tracking execution durations. Actions: `start`, `stop`, `elapsed`, `reset`, `timestamp`, `list`.

### 5.3 Tool Sets

Tool Sets are reusable presets stored in the `tool_sets` table. They can be assigned to agents (`lab_agents.tool_set_id`) or the orchestrator (`labs.orchestrator_tool_set_id`). When a tool set is assigned, its tools override the manual selection.

### 5.4 Tool Safety

| Rule | Implementation |
|------|----------------|
| **Per-lab isolation** | `python_exec` and `shell_exec` run in dedicated Docker containers (`bob-lab-{id}`), one per lab |
| **No API access** | Sandbox containers have NO access to database credentials, API source, or secrets |
| **Resource limits** | Each sandbox container has configurable memory (`tool_container_memory_mb`, default 512MB) and CPU limits |
| **Shell whitelist** | `shell_exec` validates command prefix against allowed list |
| **File isolation** | `file_read`/`file_write` scoped to `LAB_RESOURCES_ROOT/{lab_id}/` |
| **SSRF protection** | `web_extract` and `browser_navigate` block private IP addresses |
| **Output limits** | Tool output truncated at `tool_max_output_kb` (default 256KB) |
| **Call limits** | Max `tool_max_calls` (default 10) tool calls per agent per turn |
| **Timeout** | Every tool has `tool_timeout_sec` (default 30s) timeout via `asyncio.wait_for` |
| **Anti-recursion** | `call_agent` sub-agents cannot use `call_agent` themselves |
| **Memory limits** | `memory_save` content capped at 5000 chars, importance clamped 1-10 |
| **Container lifecycle** | Containers created on Run, stopped on Complete/Fail, destroyed on Delete/Reset |

### 5.5 Tool Call Parsing

The `parse_tool_calls()` function uses 3 strategies:

1. **Standard** — `<tool_call>{"name": ..., "arguments": ...}</tool_call>` (regex)
2. **Open tag** — `<tool_call>{"name": ...}` without closing tag (balanced JSON extraction)
3. **Implicit file_write** — `"Save as: filename"` pattern → generates synthetic `file_write` call (only if agent has the tool)

Additional parsing features:
- Preprocesses `# <tool_call>` comment prefixes
- `_repair_tool_json()` fixes common LLM JSON errors (bare variable names in `content`, Python expressions in `code`)
- `_try_parse_tool_call()` with repair fallback for malformed JSON

---

## 6. Call Agent System

### 6.1 Overview

Agents can directly call other agents in the same lab via the `call_agent` tool. This bypasses the orchestrator, enabling agent-to-agent collaboration without consuming orchestrator iterations.

### 6.2 Permission Model

Each agent has a `callable_agents` field — a JSON list of agent names it is allowed to call. The `call_agent` tool only appears in an agent's tool list if:
1. `call_agent` is in the agent's `tools` list
2. `callable_agents` is non-empty

### 6.3 Execution Flow

```
Agent A calls call_agent(agent_name="Agent B", instruction="Analyze this data")
    │
    ├─ Validate "Agent B" is in Agent A's callable_agents list
    ├─ Look up Agent B in the lab
    ├─ Build Agent B's messages (with its own memories, tools, system prompt)
    ├─ Call LLM via dispatcher
    ├─ Run Agent B's own tool loop (hybrid native + text)
    │     └─ Agent B CANNOT use call_agent (blocked → prevents infinite recursion)
    ├─ Store result as lab message
    └─ Return Agent B's response text to Agent A
```

### 6.4 Anti-Recursion

Sub-agents spawned via `call_agent` receive a `ToolExecutor` with `call_agent_handler=None`. Additionally, any explicit `call_agent` tool call within the sub-agent's loop returns `"Nested call_agent is not allowed."`.

---

## 7. Memory System

### 7.1 Lab Memory (Persistent per-Lab)

Stored in `lab_memories` with `scope = 'lab'`. Survives pause/resume cycles. Both the orchestrator and agents can write to lab memory via the `memory_save` tool.

### 7.2 Agent Memory (Persistent per-Agent)

Stored in `lab_memories` with `scope = 'agent'` and `agent_id` set. Only the owning agent reads its own memory.

### 7.3 Shared Memory

When `agent.share_memory = True` (or overridden by `lab.share_memory_override`), an agent's context includes memories from ALL labs, not just the current one. Uses `LabMemoryRepository.get_all_memories()`.

### 7.4 Memory Injection

Memory is injected into agent context via `_build_agent_messages()`:
- Up to 20 memories, formatted as `<memory>` block
- Sorted by importance (desc), then updated_at (desc)

### 7.5 Memory Tools

| Tool | Arguments | Description |
|------|-----------|-------------|
| `memory_save` | `key`, `content`, `importance` | Save a fact/result to lab-wide memory |
| `memory_search` | `query` | Case-insensitive keyword search across memories |

---

## 8. Resources

### 8.1 Uploaded Resources

Users can upload files (code, images, PDFs, etc.) to a lab. Files are stored on disk at `LAB_RESOURCES_ROOT/{lab_id}/` and tracked in `lab_resources`. Maximum upload size: 20MB.

### 8.2 Resource Injection

Resources are injected into agent context via `_build_agent_messages()`:
- **Text files** (code, txt, md, etc.): Content inlined in system prompt (max 50KB per file)
- **Images**: Metadata listed in system prompt, base64-encoded images attached to user message's `images` field

### 8.3 Output Files

Agent-generated files (via `file_write`, `image_generate`, `mermaid_to_img`) are stored in `LAB_RESOURCES_ROOT/{lab_id}/output/`. The API provides endpoints to list, download, read content, and view creation/modification history of output files.

---

## 9. Dispatcher / Load Balancer

### 9.1 Architecture

The `LabDispatcher` routes LLM calls across multiple GPU servers with smart load balancing.

Each LLM provider gets a `_ProviderSlot` with a concurrency semaphore:
- **Ollama**: concurrency = 1 (serial, one request at a time)
- **OpenAI / vLLM / HuggingFace**: concurrency = 4

Provider slots are **global** — shared across all labs and dispatchers.

### 9.2 Load Balancing Flow

```
dispatcher._call_with_loadbalance("llama3.1:latest", messages, ...)
    │
    ├─ Find ALL providers hosting the model
    ├─ Sort by queue_depth (least loaded first)
    ├─ Log "queue" LlmEvent
    │
    ├─ For each provider (least loaded first):
    │     ├─ Log "dispatch" LlmEvent
    │     ├─ Acquire semaphore (queues FIFO if busy)
    │     ├─ Make LLM call
    │     ├─ On success → log "response" LlmEvent → return
    │     └─ On failure → log "failed" LlmEvent → try next
    │
    └─ All providers failed → raise RuntimeError
```

### 9.3 Public Methods

| Method | Description |
|--------|-------------|
| `call_orchestrator(lab, messages, tools=None)` | Call orchestrator's model with load balancing |
| `call_agent(agent, messages, lab_id=None, tools=None)` | Call agent's model with load balancing |

---

## 10. Scheduler

### 10.1 Lab-Level CRON

A Lab can have a `cron_expression` (e.g., `0 8 * * *` = every day at 8am). The scheduler runs as a background `asyncio` task, polling every **30 seconds**.

**Flow:**
1. Query all labs with `cron_expression IS NOT NULL` and `status != "running"`
2. Use `croniter` to compute next run time from `next_run_at` (or `created_at` if never run)
3. If due: update `next_run_at` to next occurrence, create `LabScheduleLog`, start `LabRunner`, broadcast `lab.cron.triggered`

### 10.2 Agent-Level CRON

Individual agents can have their own `cron_expression` + `cron_instruction`. When triggered, the scheduler injects a message into the running lab.

**Flow:**
1. Query all agents with `cron_expression IS NOT NULL` and `is_active = TRUE`
2. Only inject into labs with `status = "running"`
3. Compute next run time from `lab.started_at` or `agent.created_at`
4. **Deduplication**: Check for existing cron injection within `POLL_INTERVAL_SEC * 2` (60s) that starts with `[CRON:{agent_name}]`
5. If not duplicate: create inject message `[CRON:{agent_name}] {instruction}` with `sender_type="system"`, `sender_name="scheduler"`, `message_type="inject"`
6. Broadcast `lab.agent.cron.triggered`

### 10.3 Implementation

```python
POLL_INTERVAL_SEC = 30

async def _scheduler_loop(session_factory):
    await asyncio.sleep(10)  # wait for startup
    while True:
        async with session_factory() as db:
            await _check_lab_crons(db, session_factory)
            await _check_agent_crons(db)
            await db.commit()
        await asyncio.sleep(POLL_INTERVAL_SEC)
```

Lifecycle managed via `start_scheduler(session_factory)` / `stop_scheduler()` in `main.py` startup/shutdown hooks.

---

## 11. Context Files

Context files are inline markdown documents stored in `labs.context_files` as JSONB:

```json
[
  {"name": "BRIEF.md", "content": "## Project Brief\nAnalyze the European EV market..."},
  {"name": "STYLE_GUIDE.md", "content": "## Writing Style\n- Formal tone..."}
]
```

They are prepended to the system prompt of both the orchestrator and all agents as:

```
<context_files>
--- BRIEF.md ---
## Project Brief
Analyze the European EV market...

--- STYLE_GUIDE.md ---
## Writing Style
...
</context_files>
```

Context files can be edited while a lab is paused. On resume, updated context is used for all subsequent LLM calls.

---

## 12. API Routes

### 12.1 Labs — prefix `/api/v1/labs`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/labs` | List all labs (with agent_count) |
| `POST` | `/labs` | Create a new lab |
| `GET` | `/labs/{lab_id}` | Get lab details |
| `PATCH` | `/labs/{lab_id}` | Update lab config |
| `DELETE` | `/labs/{lab_id}` | Delete lab (stops runner if active) |
| `POST` | `/labs/{lab_id}/duplicate` | Deep copy lab (agents, tools, resource files) |
| `POST` | `/labs/{lab_id}/run` | Start lab (query param `reset=true` clears messages/memories) |
| `POST` | `/labs/{lab_id}/reset` | Reset lab to fresh state (clears messages, memories, outputs, destroys sandbox) |
| `POST` | `/labs/{lab_id}/pause` | Pause lab |
| `POST` | `/labs/{lab_id}/resume` | Resume lab |
| `POST` | `/labs/{lab_id}/stop` | Stop lab |
| `POST` | `/labs/{lab_id}/inject` | Inject user message mid-run |
| `GET` | `/labs/{lab_id}/export` | Export lab as JSON blueprint (agents, tools, config) |
| `POST` | `/labs/import` | Import lab from JSON blueprint |

### 12.2 Lab Agents

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/labs/agents/library` | List all agents across all labs (agent library) |
| `GET` | `/labs/{lab_id}/agents` | List agents in lab |
| `POST` | `/labs/{lab_id}/agents` | Create agent |
| `PATCH` | `/labs/{lab_id}/agents/{agent_id}` | Update agent |
| `DELETE` | `/labs/{lab_id}/agents/{agent_id}` | Delete agent |

### 12.3 Lab Tools

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/labs/{lab_id}/tools` | List lab tools |
| `POST` | `/labs/{lab_id}/tools` | Create tool |
| `PATCH` | `/labs/{lab_id}/tools/{tool_id}` | Update tool |
| `DELETE` | `/labs/{lab_id}/tools/{tool_id}` | Delete tool |

### 12.4 Messages & Memory

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/labs/{lab_id}/messages` | Get execution log (query: `limit=200`, `iteration=?`) |
| `GET` | `/labs/{lab_id}/memories` | Get memories (query: `scope=?`, `limit=50`) |
| `PATCH` | `/labs/{lab_id}/memories/{memory_id}` | Update memory (toggle hidden, edit content) |

### 12.5 Resources

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/labs/{lab_id}/resources` | List uploaded resources |
| `POST` | `/labs/{lab_id}/resources` | Upload resource file (max 20MB) |
| `GET` | `/labs/{lab_id}/resources/{resource_id}/download` | Download resource |
| `GET` | `/labs/{lab_id}/resources/{resource_id}/content` | Read resource content (inline) |
| `DELETE` | `/labs/{lab_id}/resources/{resource_id}` | Delete resource |

### 12.6 Output Files

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/labs/{lab_id}/output-files` | List agent-generated output files |
| `GET` | `/labs/{lab_id}/output-files/download` | Download output file (query: `path=`) |
| `GET` | `/labs/{lab_id}/output-files/content` | Read output file content (query: `path=`) |
| `GET` | `/labs/{lab_id}/output-files/history` | File creation/modification history (query: `path=`) |

### 12.7 Tool Sets — prefix `/api/v1/tool-sets`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tool-sets` | List all tool sets |
| `POST` | `/tool-sets` | Create tool set |
| `GET` | `/tool-sets/{ts_id}` | Get tool set |
| `PATCH` | `/tool-sets/{ts_id}` | Update tool set |
| `DELETE` | `/tool-sets/{ts_id}` | Delete tool set |
| `POST` | `/tool-sets/{ts_id}/duplicate` | Duplicate tool set |

---

## 13. WebSocket Events

All lab events are broadcast server-side via `_broadcast_lab_event()` → `manager.broadcast_to_clients()`. Payload always includes `lab_id`.

| Event | Source | Payload |
|-------|--------|---------|
| `lab.started` | `_run_loop` | `name` |
| `lab.completed` | `_run_loop` | `reason` (stopped/max_iterations/max_duration/done), `summary` |
| `lab.paused` | `pause()` / `_run_loop` | `reason` |
| `lab.resumed` | `resume()` | |
| `lab.inject` | `inject()` | `message` |
| `lab.orchestrator.message` | `_run_loop` | `content` (500 chars), `iteration` |
| `lab.iteration` | `_run_loop` | `iteration` |
| `lab.task.start` | `_execute_tasks` | `agent`, `instruction` (200 chars), `iteration` |
| `lab.task.complete` | `_execute_tasks` | `agent`, `iteration` |
| `lab.task.error` | `_execute_tasks` | `agent`, `error` |
| `lab.tool.result` | `_execute_tasks` | `agent`, `tool`, `success`, `iteration` |
| `lab.file.event` | `_execute_tasks` | `agent`, `action`, `path`, `size_bytes`, `iteration` |
| `lab.error` | `_fail()` | `error` |
| `lab.agent.call` | `_make_call_agent_handler` | `caller`, `target`, `instruction` (200 chars), `iteration` |
| `lab.cron.triggered` | `_check_lab_crons` | `lab_name`, `cron_expression` |
| `lab.agent.cron.triggered` | `_check_agent_crons` | `agent_name`, `instruction` (200 chars) |

---

## 14. File Structure

```
control-plane/app/
├── models/
│   └── orchestrator.py          # Lab, LabAgent, LabTool, LabMessage, LabMemory,
│                                 # LabResource, LabScheduleLog, ToolSet, LlmEvent
├── schemas/
│   └── orchestrator.py          # All Pydantic schemas (Create/Update/Response)
├── repositories/
│   └── lab_repo.py              # LabRepo, LabAgentRepo, LabMessageRepo,
│                                 # LabMemoryRepo, LabResourceRepo, LabToolRepo,
│                                 # ToolSetRepo, LabScheduleLogRepo
├── services/
│   ├── lab_runner.py            # Core runner (strategy-agnostic)
│   ├── lab_dispatcher.py        # Model-aware load-balanced LLM routing
│   ├── tool_executor.py         # Tool execution (18 builtin tools)
│   ├── container_manager.py     # Per-lab Docker sandbox lifecycle
│   ├── lab_scheduler.py         # Cron scheduler (lab + agent level)
│   └── loop_strategies/
│       ├── __init__.py          # Strategy registry + get_strategy()
│       ├── base.py              # LoopStrategy ABC, LoopContext, actions
│       ├── plan_execute.py      # Plan & Execute (default)
│       ├── critique_refine.py   # Critique & Refine
│       └── round_robin.py       # Round Robin
├── api/routes/
│   ├── labs.py                  # Lab CRUD + lifecycle + agents + tools + resources
│   └── tool_sets.py             # Tool set CRUD
├── websocket/
│   ├── hub.py                   # WebSocket hub (broadcast)
│   └── client_handler.py        # Client WebSocket handler
└── migrations/
    ├── 003_labs.sql             # Core lab tables
    ├── 004_lab_share_memory.sql # share_memory columns
    ├── 005_lab_resources.sql    # lab_resources table
    ├── 006_lab_tool_settings.sql# tool safety settings on labs
    ├── 007_tool_sets.sql        # tool_sets table + FK columns
    └── 008_agent_cron_callable.sql # callable_agents, cron_expression, cron_instruction

sandbox/
├── Dockerfile                   # Sandbox image (CadQuery, NumPy, shell tools)
├── main.py                      # FastAPI service (python_exec, shell_exec)
└── requirements.txt             # cadquery, numpy, fastapi, uvicorn

frontend/src/components/labs/
└── LabsView.js                  # Full lab UI (list, timeline, inspector, forms)
```

---

## 15. Dependencies

Lab-specific dependencies in `control-plane/requirements.txt`:

| Package | Version | Purpose |
|---------|---------|---------|
| `croniter` | 2.0.5 | Cron expression parsing for scheduler |
| `duckduckgo-search` | 7.5.3 | Web search tool (DuckDuckGo API) |
| `playwright` | 1.49.1 | Headless Chromium for browser tools |
| `beautifulsoup4` | 4.12.3 | HTML text extraction for web_extract |
| `httpx` | 0.27.0 | Async HTTP client for web tools + sandbox communication |
| `docker` | ≥7.0 | Docker SDK for per-lab sandbox container management |

External Docker image used by `mermaid_to_img` tool: `minlag/mermaid-cli` (not installed in bob-api, runs as sibling container).

---

## 16. Per-Lab Sandbox Containers

### 16.1 Architecture (Option B)

Each lab gets its own isolated Docker container for code execution (`python_exec`, `shell_exec`). This replaces the previous shared `bob-sandbox` sidecar (Option A).

```
bob-api (Control Plane)
    │
    ├── Docker SDK (via /var/run/docker.sock)
    │
    ├──► bob-lab-a1b2c3d4e5f6  (Lab A sandbox)
    │    ├── python_exec, shell_exec
    │    ├── CadQuery, NumPy installed
    │    ├── 512MB RAM, 1 CPU (configurable)
    │    └── lab_resources volume mounted
    │
    ├──► bob-lab-f7e8d9c0b1a2  (Lab B sandbox)
    │    └── ... (independent container)
    │
    └──► bob-lab-...            (Lab N sandbox)
```

### 16.2 Container Lifecycle

| Event | Action |
|-------|--------|
| **Lab Run** (`POST /labs/{id}/run`) | `ensure_sandbox()` — create container if missing, start if stopped |
| **Tool Call** (`python_exec`, `shell_exec`) | `ensure_sandbox()` — lazy creation if container doesn't exist |
| **Lab Complete/Fail** | `stop_sandbox()` — stop container (preserves state, saves resources) |
| **Lab Reset** (`POST /labs/{id}/reset`) | `destroy_sandbox()` — remove container for clean state |
| **Lab Delete** (`DELETE /labs/{id}`) | `destroy_sandbox()` — remove container |
| **API Startup** | `cleanup_orphaned()` — remove all `bob-lab-*` containers from previous runs |

### 16.3 Container Configuration

| Setting | Default | Source |
|---------|---------|--------|
| Image | `bob-manager-bob-sandbox:latest` | `SANDBOX_IMAGE` env var |
| Network | `bob-manager_bob-network` | `DOCKER_NETWORK` env var |
| Volume | `bob-manager_lab_resources` | `LAB_RESOURCES_VOLUME` env var |
| Memory | 512 MB | `labs.tool_container_memory_mb` column |
| CPUs | 1.0 | `SANDBOX_CPUS` env var |
| Container name | `bob-lab-{lab_id[:12]}` | Derived from lab UUID |
| Labels | `bob-manager.role=lab-sandbox`, `bob-manager.lab-id=<uuid>` | For cleanup filtering |

### 16.4 Security Isolation

| Concern | Protection |
|---------|------------|
| API source code | Container has NO access to `/app` (API code) |
| Database credentials | Container has NO `DATABASE_URL`, `AGENT_SECRET`, or `JWT_SECRET` |
| Inter-lab isolation | Each lab's code runs in a separate container with its own PID namespace |
| Resource exhaustion | Per-container Docker cgroup limits (memory + CPU) |
| Filesystem | Shared `lab_resources` volume, but sandbox code validates `lab_id` paths |

### 16.5 Building the Sandbox Image

The sandbox image is built via Docker Compose but not started as a persistent service:

```bash
# Build image only (profiles: [build-only] prevents auto-start)
docker compose build bob-sandbox
```

The image includes: Python 3.12, CadQuery, NumPy, FastAPI/Uvicorn, and system tools (jq, bc, curl, wget).
