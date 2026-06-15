# Bob Labs — Agents And Orchestration

## Scope

This document summarizes the implemented orchestration behavior across the orchestrator, Labs runtime, agent execution model, and standalone agent usage in conversations.

## Agent Surfaces

Agents exist in two forms:

- **Global Agents** (`ai_agents` table, managed in the Agents tab) — Reusable agent definitions with name, description, system prompt, model, temperature, max tokens, and tools. Can be assigned to conversations or imported into labs.
- **Lab Agents** (`lab_agents` table, managed per-lab) — Lab-specific agent instances with additional fields: role, callable agents, cron scheduling, tool sets, and memory sharing. Lab agents can be **saved to the global Agents list** via the "Save to Agents" button.
- **Solo Agent Instances** — Labs flagged `acl.tag = 'agent_instance'` that wrap a single agent so it can be run with full Lab capabilities (sandbox, resources, memory, RAG, Web3, server access). Managed from the **Agents tab** — see [AGENTS_TAB.md](AGENTS_TAB.md) for the full UI/UX, data flow, and endpoint catalogue.

### Agents in Conversations

When an AI Agent is assigned to a conversation:
- The agent's system prompt is injected as the conversation's system context
- The agent's model and temperature settings are used for inference
- The agent's tools are available for tool calling in chat

### Agents in Labs

Lab agents participate in multi-agent orchestration loops, receiving tasks from the orchestrator and executing them with their assigned tools.

## Orchestrator Role

The orchestrator is the central decision-maker for a Lab. Depending on the loop strategy, it can:

- analyze the current state of the Lab
- decide whether more work is needed
- create task assignments for one or more agents
- call tools directly if tools are assigned to it
- synthesize a final answer
- pause the Lab for operator input

The orchestrator prompt is assembled from strategy instructions, tool policy, custom prompt content, context files, memory index, uploaded resources, output files, and execution budget details.

## Lab Runtime

The `LabRunner` is the execution engine that turns orchestration decisions into actual work. It is responsible for:

- loading Lab state and active agents
- instantiating the configured loop strategy
- resolving tool sets and direct tool assignments
- calling the orchestrator model
- parsing orchestration output
- dispatching agent tasks concurrently
- handling completion, pause, failure, and budget limits

## Supported Loop Strategies

Current strategy types described in the repository:

- `plan_execute`
- `critique_refine`
- `round_robin`
- `solo_agent` — single LabAgent driven by native tool-calling, no orchestrator JSON layer. Used by solo instances (Agents tab) and consumer-app `/run_agent`.

The loop strategy abstraction separates decision logic from runtime execution mechanics, which makes behavior extensible without rewriting the runner.

## Agent Definition Model

Each Lab agent can define:

- name and role
- system prompt
- model selection (any synced provider model — Ollama, cloud APIs, or Claude CLI models, which appear namespaced as `claude-cli:<id>`; see [CLAUDE_CLI.md](CLAUDE_CLI.md))
- execution backend (`native` or `hermes`)
- temperature and token limits
- tools or tool set assignment
- memory-sharing behavior
- allowed callable agents
- optional cron injection settings

This makes each agent a reusable operational unit rather than a temporary prompt fragment.

## Execution Backends

Agents run on one of two backends, selected per agent in the edit form:

- **`native`** (default) — Bob Labs drives the LLM loop described below: prompt assembly, hybrid tool calling, bounded tool loop.
- **`hermes`** — the whole task is delegated to a dedicated per-agent container running the real NousResearch Hermes agent, which uses its own loop, tools, and persistent memory and returns one final result. The agent's model selection still applies (it is the LLM Hermes thinks with, switchable per task). Bob Labs tools and `call_agent` do not apply to hermes agents.

The backend field follows the agent everywhere (template cascade, duplication, instances, lab blueprints, consumer-app APIs). See [HERMES.md](HERMES.md) for the container lifecycle, the task-completion protocol, and session memory.

## Agent Execution Behavior

When the orchestrator emits tasks:

1. Task assignments are recorded in the Lab message log.
2. Agents run concurrently through the dispatcher.
3. Each agent receives its own system prompt, resources, memory index, and tool descriptions.
4. The agent may call tools in a bounded loop.
5. Final agent output is stored and broadcast to the UI.

This design allows one orchestrator turn to fan out across multiple specialist agents.

## Tool Calling Model

The platform supports a hybrid tool loop:

- native function-calling for models that support structured tool calls
- text-based tool call parsing for models that do not

The runner attempts native tool calls first, then falls back to parsing `<tool_call>` blocks. This broadens model compatibility without forcing a single provider capability model.

Note: Claude CLI models (`claude-cli:*`) are text-only — the wrapper ignores tool schemas and never returns tool calls. Use them for tool-less agents; see [CLAUDE_CLI.md](CLAUDE_CLI.md).

## Agent-To-Agent Calls

Agents may call other agents through `call_agent` when explicitly allowed by `callable_agents`.

Important runtime behavior:

- permissions are explicit
- sub-agents cannot recursively call more agents
- the sub-agent still receives its own prompt, tools, and memory

This makes direct collaboration possible while preventing uncontrolled recursion.

## Memory Model

The documented memory scopes are:

- Lab-wide memory
- agent-specific memory
- optional shared cross-Lab memory

Memories are indexed into prompts in compact form, while deeper retrieval is handled through tools such as `memory_search`.

## Persistence And Operator Control

Labs are designed as persistent workspaces rather than ephemeral prompts. Operators can:

- run a Lab
- pause and resume execution
- inject new instructions while a Lab is active
- reset a Lab
- duplicate a Lab
- export or import a Lab blueprint

This is a key difference from simple chat applications.
