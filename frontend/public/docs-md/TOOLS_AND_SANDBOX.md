# Bob Labs — Tools & Sandbox

## Overview

Agents interact with the world through a managed set of built-in tools. Tools are defined in `BUILTIN_TOOLS` (in `app/services/tools/__init__.py`, auto-discovered from `tool_*.py` modules) and executed by `ToolExecutor`. Each tool returns `{"success": bool, "output": str}` with optional `file_event` for created/edited files.

Tools are available in two contexts:
- **Labs** — Assigned to lab agents or orchestrators via tool sets or direct selection.
- **Conversations** — Selected per-conversation via the tools panel in the UI. Enables tool calling in chat.

### Builtin Tools API

The full list of registered tools is served dynamically:

```
GET /api/v1/orchestrator/builtin-tools
```

Returns an array of `{name, description, expandable?, subTools?}`. The frontend fetches this on mount instead of maintaining a hardcoded list. Adding a new `tool_*.py` module to the backend automatically makes its tools available everywhere.

## Tool Reference (34 Tools)

### Reasoning

| Tool | Description | Parameters |
|------|-------------|------------|
| `think` | Private reasoning step. Output is not shown to other agents. | `thought` (string, required) |

### Memory

| Tool | Description | Parameters |
|------|-------------|------------|
| `memory_save` | Save a fact or result to lab memory for later retrieval. | `key` (string, required), `content` (string, required), `importance` (int 1–10, default 5) |
| `memory_search` | Search lab memories by keyword. | `query` (string, required) |
| `handle_memory` | Manage agent memories: list, hide, or show. Hidden memories are excluded from agent prompts. | `agent_name` (string, required), `action` (string: list/hide/show, required), `memory_ids` (string, comma-separated, for hide/show) |

### File I/O

| Tool | Description | Parameters |
|------|-------------|------------|
| `file_read` | Read a file from the lab workspace (relative path). | `path` (string, required) |
| `file_write` | Write content to a file in the lab output folder (relative path). | `path` (string, required), `content` (string, required) |

### Code Execution

| Tool | Description | Parameters |
|------|-------------|------------|
| `python_exec` | Execute Python code in a sandboxed container. Returns stdout/stderr. | `code` (string, required) |
| `shell_exec` | Execute a whitelisted shell command in a sandboxed container. | `command` (string, required) |

### Web

| Tool | Description | Parameters |
|------|-------------|------------|
| `web_search` | Search the web using DuckDuckGo. | `query` (string, required), `max_results` (int, default 5) |
| `web_extract` | Fetch a URL and extract its text content. | `url` (string, required) |
| `browser_navigate` | Open a URL in headless Chromium and return rendered text. | `url` (string, required) |
| `browser_snapshot` | Take a text snapshot of the current browser page (accessibility tree). Requires `browser_navigate` first. | *(none)* |

### Media Generation

| Tool | Description | Parameters |
|------|-------------|------------|
| `image_generate` | Generate an image from a text prompt via configured API. | `prompt` (string, required), `width` (int, default 1024), `height` (int, default 1024) |
| `audio_generate` | Generate audio via GPU script runners. | `script` (string, required), `prompt` (string, required), `duration_sec` (number), `extra_args` (object) |
| `media_pipeline` | Generate media via registered GPU pipeline backends. | `pipeline` (string, required), `prompt` (string, required), `params` (object) |
| `audio_mix` | Mix, concatenate, normalize, trim audio files using FFmpeg (CPU). | `operation` (string: mix/concat/volume/fade/normalize/convert/trim/eq, required), `input_files` (array, required), `output_file` (string, required), `params` (object) |
| `video_generate` | Generate MP4 video from React/TSX code via Remotion. | `code` (string, required), `width` (int, default 1920), `height` (int, default 1080), `fps` (int, default 30), `duration_in_frames` (int, default 120), `props` (object) |

### RAG (Retrieval-Augmented Generation)

| Tool | Description | Parameters |
|------|-------------|------------|
| `rag_list_collections` | List RAG collections this lab can access. | *(none)* |
| `rag_search` | Search an accessible RAG collection using semantic similarity. | `query` (string, required), `collection` (string, required), `top_k` (int, default 5), `mode` (string: local/global/hybrid), `filter` (object), `score_threshold` (number 0–1) |
| `rag_ingest` | Ingest text or a workspace file into a RAG collection. | `collection` (string, required), `filename` (string, required), `source_file` (string), `content` (string), `metadata` (object) |

### Diagrams

| Tool | Description | Parameters |
|------|-------------|------------|
| `mermaid_to_img` | Convert a Mermaid diagram file to SVG or PNG. | `input_path` (string, required), `output_format` (string: svg/png, default svg) |
| `excalidraw` | Create an Excalidraw diagram, render to PNG, upload for shareable link. | `elements` (string JSON array, required), `filename` (string, default "diagram"), `dark_mode` (string: true/false) |

### Communication

| Tool | Description | Parameters |
|------|-------------|------------|
| `call_agent` | Call another agent in the same lab for a sub-task. | `agent_name` (string, required), `instruction` (string, required) |
| `mail` | Send and read emails via SMTP/IMAP. | `action` (string: send/read, required), `to` (string), `subject` (string), `body` (string), `html` (string), `folder` (string), `limit` (int), `search` (string) |
| `twitter` | Post tweets or read Twitter/X timeline, mentions, and search. | `action` (string: post/read, required), `text` (string, max 280), `feed` (string: timeline/mentions/search), `query` (string), `limit` (int) |

### Data

| Tool | Description | Parameters |
|------|-------------|------------|
| `blockchain` | Query on-chain data for Ethereum, Base, and Solana. | `action` (string: balance/transactions/token_transfers/token_info, required), `address` (string, required), `chain` (string: ethereum/base/solana), `limit` (int, default 20) |
| `youtube` | Download audio from YouTube videos or list channel videos. | `action` (string: download_audio/list_channel, required), `url` (string), `channel_url` (string), `format` (string: mp3/wav/m4a/flac/ogg), `max_videos` (int, default 20) |

### Utility

| Tool | Description | Parameters |
|------|-------------|------------|
| `clock` | Time tracking: start/stop/elapsed/reset/timestamp/list timers. | `action` (string, required), `name` (string, default "default") |

## Execution Boundaries

Tools execute in different contexts depending on their category:

| Context | Tools | Security |
|---------|-------|----------|
| **Control plane** (in-process) | think, memory_*, handle_memory, call_agent, clock, blockchain, web_*, rag_*, mail, twitter, youtube | Access to DB, full network |
| **Sandbox container** (isolated) | python_exec, shell_exec | No API/DB/secret access; resource limits |
| **External HTTP** | image_generate, audio_generate, media_pipeline, video_generate, audio_mix | Routed through control plane |
| **Browser** | browser_navigate, browser_snapshot, excalidraw | Playwright in sandbox |
| **Filesystem** | file_read, file_write, mermaid_to_img | Scoped to lab workspace |

## Sandbox Model

Each lab gets a dedicated sandbox container for bounded code and shell execution.

### Container Lifecycle

| Event | Action |
|-------|--------|
| First `python_exec` or `shell_exec` call | Lazy container creation |
| Lab starts | Container started |
| Lab completes or fails | Container stopped |
| Lab reset or deleted | Container destroyed |
| API startup | Orphaned containers cleaned up |

### Resource Limits

| Limit | Default | Configurable |
|-------|---------|-------------|
| Memory | 2 GB | `tool_container_memory_mb` per lab |
| CPUs | 2 | — |
| Output size | 256 KB | `tool_max_output_kb` per lab |
| Timeout | 60 seconds | `tool_timeout_sec` per lab |
| Max tool calls | Configurable per lab | `tool_max_calls` |

### Shell Whitelist

The sandbox only allows commands starting with these tokens:

```
curl, wget, python3, python, pip, pip3,
cat, head, tail, wc, grep, awk, sed, sort, uniq,
ls, find, echo, date, whoami, uname, pwd,
jq, bc, tr, cut, tee, xargs,
ffmpeg, ffprobe, yt-dlp,
freecadcmd, freecad, kicad-cli
```

### File Scope

- Uploaded resources: stored under the lab resource root (`/data/lab_resources/{lab_id}/`)
- Output files: written under the lab output directory (`output/`)
- Directory traversal outside the workspace is blocked

## Safety Controls

| Control | Description |
|---------|-------------|
| Per-lab isolation | Each lab gets its own sandbox container and file namespace |
| Resource limits | Memory, CPU, output size, and timeout caps |
| Shell prefix validation | Only whitelisted commands execute |
| Output truncation | Tool output capped at `max_output_kb` |
| Timeout enforcement | `asyncio.wait_for()` with per-lab timeout |
| Call count limits | Max tool calls per agent turn prevents runaway loops |
| Anti-recursion | `call_agent` depth limited to prevent infinite delegation |
| SSRF protection | Web tools validate URLs and block internal network access |
| Tool availability check | Only tools in the agent's configured tool list are executable |

## Tool Call Loop

During an orchestrator or agent turn, the runtime executes a multi-step tool loop:

1. Model generates a response
2. Runtime detects tool calls (native function calling or text-parsed `<tool_call>` blocks)
3. Tool availability validated against the agent's tool set
4. Tools executed (potentially in parallel for independent calls)
5. Results fed back into the conversation
6. Model re-called with results
7. Loop continues until model produces a final response or max tool calls reached

The loop supports both **native tool calling** (Ollama, vLLM, OpenAI function calling) and **text-parsed fallback** for models without native support.

## Tool Sets

Tools can be organized into reusable **Tool Sets** — named collections of tools that can be assigned to agents or orchestrators. Tool sets are managed via `/api/v1/tool-sets` (CRUD + duplicate).

When an agent has a tool set assigned:
1. The tool set's tools are loaded
2. Any manually-selected tools are merged (union)
3. The combined list determines what the agent can use

Multiple tool sets can be assigned to a single agent or orchestrator.

## Tool Configurations

Some tools require external API credentials. These are managed via `/api/v1/tool-configs`:

| Tool | Required Configuration |
|------|----------------------|
| `mail` | SMTP/IMAP server, credentials |
| `twitter` | Twitter API keys (consumer key/secret, access token/secret) |

Sensitive values are masked in API responses.
