# Bob Labs — Agents Tab

## Overview

The **Agents** tab is the unified workspace for managing reusable agent **templates** (the global agent library) and running **solo agent instances**. A solo agent instance is a Lab whose ACL is tagged `agent_instance` and which contains a single agent — it gives every template the power of a Lab (sandbox, resources, output files, memory, RAG, Web3, server access, conversation injection) without forcing the operator to build a multi-agent orchestration scenario.

The tab mirrors the Labs tab visually so operators move between the two with zero cognitive cost: same timeline feed, same status badges, same Run/Pause/Resume/Stop/Reset top bar, same right-panel inspector with Agent / Resources / Memory / Links sub-tabs.

## Layout

```
┌──────────────┬──────────────────────────────────────┬──────────────┐
│ LEFT          │ CENTER                                │ RIGHT         │
│ Templates +   │ Dashboard / Editor / Feed /           │ Stats         │
│ Instance list │   File viewer / Prompt editor         │   (template)  │
│               │                                       │ Inspector     │
│               │                                       │   (instance)  │
└──────────────┴──────────────────────────────────────┴──────────────┘
```

### Left rail
- **Templates** — entries from the global library (`library_agents` table). A template badge shows the active/inactive state and the tool count.
- **Instance Agents** — every Lab where `acl.tag = 'agent_instance'`. Each row exposes Run/Pause/Resume/Stop/Delete inline buttons and the live status badge (`created`, `running`, `paused`, `completed`, `failed`).
- The "+ New" button creates a fresh template; templates can be turned into solo instances with the spark button.

### Center pane
The center pane has five mutually exclusive states:

1. **Dashboard** — default view when nothing is selected. Lists templates and recent instances side by side.
2. **Template editor** — full agent form (name, description, model, temperature, max tokens, system prompt, tools, tool sets, callable agents, cron, anti-loop, memory sharing). Reuses the `AgentEditForm` component from the Labs tab so the field set is identical.
3. **Instance feed** — Labs-style timeline:
   - Top bar: `Run`, `Continue`, `Reset`, `Pause`, `Resume`, `Stop`, expand-all toggle, close.
   - Messages styled with the Labs color scheme: orange for `file_event`, purple/violet for `tool_call` / `tool_result`, green for `result`, blue for `task`, yellow for `inject` (operator messages), red for `error`, cyan for `summary`.
   - Avatar color: green = `agent`, blue = `orchestrator`, red = `user`, neutral = `system`.
   - Tool calls render the same expandable terminal-style block as Labs (Python / Shell / SQL get a code-window header).
   - An output-file chip strip below the feed jumps directly to the central file viewer.
   - A bottom inject box sends an operator message (POST `/labs/{lab_id}/inject` with `{ "content": "..." }`).
4. **File viewer** — opened by clicking an output chip in the feed *or* a resource/output card in the right inspector. Renders images, audio, video via authenticated blob URLs, and text/JSON inline; binary files fall back to a download button.
5. **Prompt editor** — full-screen editor for an agent's system prompt with a Save button that calls `PATCH /labs/{lab_id}/agents/{agent_id}`.

### Right pane

When a **template** is selected the right pane shows aggregated **stats**:
- Labs / messages / successes / failures / anti-loop triggers / total tokens.
- Last active timestamp.
- **Solo agents** section: instances of this template (each row navigates to the instance feed).
- **Used in labs** section: real (multi-agent) labs that include this template (each row deep-links to `#labs?lab=<id>`).

When an **instance** is selected the right pane shows the **Inspector** with four tabs:

| Tab | Content |
|-----|---------|
| Agent | Read-only card of the live `lab_agent` configuration with an edit button that opens the prompt editor or full agent form. |
| Resources | Inputs (uploaded resources) and Outputs (files written by the agent into its sandbox). Clicking a row opens the central file viewer; the ⬇ button downloads. |
| Memory | Per-agent memory entries with hide toggle. |
| Links | RAG collection access, Web3 wallet access, server access — all toggleable on the fly. |

## Data Model

| Concept | Storage |
|---------|---------|
| Template | `library_agents` row |
| Solo instance | `labs` row + `lab_agents` row, with `acl.tag = 'agent_instance'` |
| Messages | `lab_messages` (same table as Labs) |
| Output files | Lab sandbox volume, surfaced via `/labs/{id}/output-files` |
| Resources | `lab_resources` (same table as Labs) |

This deliberate reuse means **anything you can do in a Lab, you can do in a solo agent**, and an instance can be promoted to a multi-agent Lab simply by adding more `lab_agents` rows from the Labs tab.

## API Endpoints Used

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/library/agents` | List templates |
| POST | `/library/agents` | Create template |
| PATCH | `/library/agents/{id}` | Update template |
| DELETE | `/library/agents/{id}` | Delete template |
| GET | `/library/agents/{id}/labs` | Labs that reference this template |
| GET | `/library/agents/{id}/stats` | Aggregated stats |
| POST | `/library/agents/{id}/instantiate` | Create a solo lab from a template |
| GET | `/labs?tag=agent_instance` | List solo instances |
| GET | `/labs/{id}/messages` | Feed |
| GET | `/labs/{id}/agents` | Lab agent configs |
| GET | `/labs/{id}/resources` | Inputs |
| GET | `/labs/{id}/output-files` | Outputs |
| GET | `/labs/{id}/output-files/{path}/content` | Render a file inline |
| GET | `/labs/{id}/resources/{rid}/content` | Render a resource inline |
| POST | `/labs/{id}/run` `pause` `resume` `stop` `reset` | Execution controls |
| POST | `/labs/{id}/inject` | Send operator message — body `{ "content": "..." }` |
| PATCH | `/labs/{id}/agents/{agent_id}` | Edit live agent (e.g., update system prompt) |
| GET | `/labs/{id}/memories` + `PATCH` | View / hide memories |
| GET / POST | `/labs/{id}/rag-access`, `/web3-access`, `/server-access` | Manage links |

## Polling

While an instance is `running`, the feed, memories, and output files are refreshed every 3 s — same cadence as the Labs tab.

## Status Lifecycle

`created` → `running` ⇄ `paused` → `completed` | `failed`
- `Run` is shown when status is `created`.
- `Continue` + `Reset` are shown when status is `completed` or `failed`.
- `Pause` is shown when running, `Resume` when paused.
- `Stop` is shown whenever the lab is active (`running` or `paused`).

## Cross-references

- See [LABS.md](LABS.md) for the underlying Lab runtime, loop strategies, and execution engine.
- See [AGENTS_AND_ORCHESTRATION.md](AGENTS_AND_ORCHESTRATION.md) for the agent execution model.
- See [TOOLS_AND_SANDBOX.md](TOOLS_AND_SANDBOX.md) for the tool catalog available to every agent.
- See [PROMPT_STRUCTURE.md](PROMPT_STRUCTURE.md) for how the system prompt is assembled at run-time.
