# Prompt Structure Documentation

This document describes how system prompts are assembled for both the **orchestrator** and **agents** in a lab run.

---

## 1. Orchestrator Prompt

Built by `build_strategy_system()` in `control-plane/app/services/loop_strategies/base.py`.

The system prompt is assembled in this order:

```
┌─────────────────────────────────────────────┐
│ 1. Base Strategy Prompt                     │
│    (or strategy_prompt_override if set)      │
├─────────────────────────────────────────────┤
│ 2. Tools Policy                             │
│    - "You cannot act — only delegate" OR    │
│    - Direct tools description (if orch has  │
│      tools assigned)                        │
├─────────────────────────────────────────────┤
│ 3. Custom Orchestrator Prompt               │
│    (lab.orchestrator_prompt — user-written)  │
├─────────────────────────────────────────────┤
│ 4. Context Files (legacy JSONB)             │
│    <context_files>...</context_files>        │
├─────────────────────────────────────────────┤
│ 5. Memory Index (Level-0)                   │
│    <memory_index>                            │
│    - [key] imp=N age preview…               │
│    </memory_index>                           │
│    💡 Use memory_search(query) for full text │
├─────────────────────────────────────────────┤
│ 6. Auto Sweep Instruction (optional)        │
│    (if lab.auto_sweep_memory is enabled)     │
├─────────────────────────────────────────────┤
│ 7. Uploaded Resources (metadata only)       │
│    <uploaded_resources>                      │
│    - filename (type, size)                   │
│    Use file_read(path="<filename>") to read  │
│    </uploaded_resources>                     │
│    <images>                                  │
│    - image.png (image/png, 1234 bytes)      │
│    </images>                                 │
├─────────────────────────────────────────────┤
│ 8. Output Files                             │
│    <output_files>                            │
│    output/file.stl (12,345 bytes)            │
│    </output_files>                           │
├─────────────────────────────────────────────┤
│ 9. Budget                                   │
│    Iteration 3/20 | elapsed 45s/3600s       │
└─────────────────────────────────────────────┘
```

### Details

**1. Base Strategy Prompt** — Each strategy (sequential, parallel, pipeline, swarm, single) provides its own base prompt template that includes placeholders like `{lab_name}` and `{agent_descriptions}`. If `strategy_prompt_override` is set on the lab, it replaces the default template entirely.

**2. Tools Policy** — If the orchestrator has tools assigned (`orch_tool_names`), the static "you cannot act" block is replaced with a description of available tools. If the orchestrator also has agents, it can both use tools directly and delegate to agents.

**3. Custom Orchestrator Prompt** — Free-text instruction set by the user in the lab configuration (`lab.orchestrator_prompt`). Appended as "## Additional Instructions".

**4. Context Files** — Legacy inline JSONB content stored on the lab object. Each entry has a `name` and `content` field.

**5. Memory Index** — Top 30 memories sorted by importance, showing key, importance score, age, and an 80-char preview. Agents use `memory_search(query)` to retrieve full content (Level-1 access).

**6. Auto Sweep** — If enabled, instructs the orchestrator to periodically review and hide outdated memories.

**7. Uploaded Resources** — Lists resource files by name, type, and size. Content is **not** inlined. Agents use `file_read(path="<filename>")` to read content on demand. Image resources are listed separately and their bytes are attached to the user message for vision models.

**8. Output Files** — Lists all files under the lab's `output/` directory with sizes.

**9. Budget** — Current iteration number (and max), elapsed time (and max duration).

---

## 2. Agent Prompt

Built by `_build_agent_messages()` in `control-plane/app/services/lab_runner.py`.

The agent receives a two-message array: `[system, user]`.

### System Message

```
┌─────────────────────────────────────────────┐
│ 1. Agent System Prompt                      │
│    agent.system_prompt or default role text  │
├─────────────────────────────────────────────┤
│ 2. Context Files (legacy JSONB)             │
│    <context_files>...</context_files>        │
├─────────────────────────────────────────────┤
│ 3. Uploaded Resources (metadata only)       │
│    <uploaded_resources>                      │
│    - filename (type, size)                   │
│    Use file_read(path="<filename>") to read  │
│    </uploaded_resources>                     │
│    <images>                                  │
│    - image.png (image/png, 1234 bytes)      │
│    </images>                                 │
├─────────────────────────────────────────────┤
│ 4. Tool Descriptions                        │
│    (from format_tool_descriptions)           │
├─────────────────────────────────────────────┤
│ 5. Memory Index (Level-0)                   │
│    Same format as orchestrator               │
├─────────────────────────────────────────────┤
│ 6. Output Files                             │
│    <output_files>                            │
│    output/file.stl (12,345 bytes)            │
│    </output_files>                           │
└─────────────────────────────────────────────┘
```

### User Message

Contains the orchestrator's instruction for the agent task. If image resources exist, their base64-encoded bytes are attached in an `images` field for vision-capable models.

---

## 3. Resource Handling

Resources are uploaded files attached to a lab. They are stored on disk at:
```
LAB_RESOURCES_ROOT / <lab_id> / <filename>
```

The `file_read` tool resolves paths relative to the lab workspace (`LAB_RESOURCES_ROOT / <lab_id>`), so agents can read a resource named `cadquery_generator.py` with:
```
file_read(path="cadquery_generator.py")
```

**Important**: Resource file content is NOT included in prompts. Only a listing of names, types, and sizes is provided. This keeps prompt sizes small regardless of resource file sizes. Agents read file content on demand via `file_read`.

---

## 4. Memory System

Memories are stored per-lab with the following attributes: `key`, `content`, `importance`, `scope`, `agent_id`.

- **Level-0 (Index)**: Injected into system prompts — key + importance + 80-char preview
- **Level-1 (Full)**: Retrieved on demand via `memory_search(query)` tool
- **Scopes**: `lab` (shared), `agent` (per-agent), `orchestrator`
- Memories can be hidden via `is_hidden` flag (auto-sweep or manual)
- Maximum 30 entries in the index, sorted by importance then recency
