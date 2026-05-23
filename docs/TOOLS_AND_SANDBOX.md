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

## Tool Reference (40 Tools)

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
| `comfyui` | Drive a ComfyUI server: list models, upload inputs, queue workflows, check status, fetch node types. | `action` (string: upload_input/queue_workflow/get_status/list_models/interrupt/get_node_types, required), `input_filename` (string), `workflow` (object), `folder_type` (string), `timeout_sec` (int), `provider` (string) |

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
| `media_post` | Publish a post to a configured social-media account. Credentials resolve server-side from `social_<platform>` config; the agent only references an account by `account_id`. | `platform` (string: x/linkedin/instagram/facebook, required), `account_id` (string), `content` (string), `media_urls` (string, comma-sep), `action` (string: post/list_accounts) |
| `postiz` | Schedule, draft, and analyse social posts via the Postiz Public API. Single Postiz instance per deployment. | `action` (string, required), `integration_ids` (string), `content` (string), `schedule_date` (ISO 8601), `post_type` (string), `media_urls` (string), `settings` (JSON string), `post_id` (string), `status` (string), `media_path` (string), `tool_method` (string), `tool_data` (JSON string), `days` (int), `start_date`, `end_date` |

### Data

| Tool | Description | Parameters |
|------|-------------|------------|
| `blockchain` | Query on-chain data for Ethereum, Base, and Solana via Blockscout. | `action` (string: balance/transactions/token_transfers/token_info, required), `address` (string, required), `chain` (string: ethereum/base/solana), `limit` (int, default 20) |
| `defi_data` | DeFi market data: token prices, protocol/chain TVL, yields, DEX pairs, gas tracker. No API keys required (CoinGecko + DeFiLlama + DEX Screener). | `action` (string, required), `query` (string), `token_ids` (string), `contract` (string), `chain` (string), `project` (string), `min_apy` (string), `min_tvl` (string), `limit` (int) |
| `youtube` | Download audio from YouTube videos or list channel videos. | `action` (string: download_audio/list_channel, required), `url` (string), `channel_url` (string), `format` (string: mp3/wav/m4a/flac/ogg), `max_videos` (int, default 20) |
| `gouv_data_fr` | Query data.gouv.fr (French national open-data portal) public APIs — catalog search, dataset metadata, organizations, usage metrics, tabular row queries. Read-only, no key. Pair with the optional `templates/skills/datagouv.md` skill for workflow detail. | `action` (string: search_datasets/get_dataset/search_organizations/get_organization/get_dataset_metrics/query_tabular/get_resource, required), `params` (object: action-specific shape — see tool docstring or skill) |

### Database

The agent's per-lab SQLite database. Tools are sandboxed: writes apply only to the lab's DB, never the control-plane DB.

| Tool | Description | Parameters |
|------|-------------|------------|
| `db_query` | Execute a read-only SELECT and return rows with column names. | `sql` (string, required), `params` (array) |
| `db_execute` | Execute a write statement (CREATE/INSERT/UPDATE/DELETE). | `sql` (string, required), `params` (array) |
| `db_schema` | Show tables, columns, types, and row counts. | *(none)* |

### Web3

| Tool | Description | Parameters |
|------|-------------|------------|
| `trading` | Crypto trading on Ethereum / Base / BNB. List wallets, send native or token transfers, get swap quotes, approve and swap on DEX, manage positions. Requires `TRADING_PRIVATE_KEYS` env. | `action` (string, required), `chain` (string), `wallet`, `to`, `amount`, `token`, `from_token`, `to_token`, `spender`, `position_id`, `token_symbol`, `entry_price`, `stop_loss`, `take_profit`, `notes`, `limit` |
| `web3_portfolio` | Portfolio tracking for tracked wallets: list, balances, transactions, totals, history. | `action` (string: list_addresses/wallet_balances/wallet_transactions/portfolio_total/portfolio_history, required), `address_id`, `chain`, `hours` |
| `trustless_otc` | P2P OTC trading via the TrustlessOTC API: register, login, mint API keys, list/place/cancel orders, manage wallets. | `action` (string, required) plus action-specific args (`username`, `password`, `chain`, `symbol`, `token_sell`, `token_buy`, `amount_*`, `order_id`, `tx_hash`, `address`, etc.) |

### Operations

| Tool | Description | Parameters |
|------|-------------|------------|
| `control_server` | Run shell commands on linked control servers (SSH-managed, configured per-lab). | `action` (string: list_servers/execute/execute_all, required), `server_name` (string), `command` (string), `timeout` (int, default 30, max 120) |

### Utility

| Tool | Description | Parameters |
|------|-------------|------------|
| `clock` | Time tracking: start/stop/elapsed/reset/timestamp/list timers. | `action` (string, required), `name` (string, default "default") |

## Skills

Some tools pair with an optional **skill file** — an agent-readable Markdown doc
that captures workflow nuance the tool's short JSON-Schema description can't
carry. Skills live under `templates/skills/` in the repo. They are **not**
auto-loaded: a lab opts in explicitly via its blueprint's `context_files` array,
which materializes the file into the sandbox at `<name>` (relative to the lab workspace) so the agent
can `file_read` it when its system prompt directs it to.

| Skill file | Pairs with | Source |
|---|---|---|
| `datagouv.md` | `gouv_data_fr` | Synced from [datagouv/datagouv-skill](https://github.com/datagouv/datagouv-skill) (MIT) |

See [templates/skills/README.md](../templates/skills/README.md) for the opt-in
convention and how to add a new skill.

## Execution Boundaries

Tools execute in different contexts depending on their category:

| Context | Tools | Security |
|---------|-------|----------|
| **Control plane** (in-process) | think, memory_*, handle_memory, call_agent, clock, blockchain, defi_data, web_*, rag_*, mail, twitter, media_post, postiz, youtube, trading, web3_portfolio, trustless_otc | Access to DB, full network |
| **Sandbox container** (isolated) | python_exec, shell_exec | No API/DB/secret access; resource limits |
| **External HTTP** | image_generate, audio_generate, media_pipeline, video_generate, audio_mix, comfyui | Routed through control plane |
| **Browser** | browser_navigate, browser_snapshot, excalidraw | Playwright in sandbox |
| **Filesystem** | file_read, file_write, mermaid_to_img | Scoped to lab workspace |
| **Per-lab SQLite** | db_query, db_execute, db_schema | Writes scoped to the lab's own DB |
| **SSH to linked servers** | control_server | Per-lab server registry; commands logged |

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

Some tools need credentials before they work. The control plane uses two storage patterns and one envelope. Today both stores hold values **plaintext at rest** — encryption-at-rest is a separate, planned task.

### Storage rule

> **User-identity credentials** (a mailbox, a social-media account) → **multi-account** rows in `tool_configs.<type>.config.accounts[]`. Agents reference them by `account_id` at call time; raw secrets never reach the agent.
>
> **External service credentials** (a Postiz API instance, an OTC API key) → **singleton** flat-config row in `tool_configs.<type>.config`.

The two patterns coexist; the table below names which applies per tool.

### Per-tool configuration

| Tool | Storage | Where to set | Required keys |
|------|---------|---------------|----------------|
| `mail` | `tool_configs.mail` (singleton, **migration to multi-account is planned**) | Settings → Tool Configs → Mail | `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_from`, `smtp_tls`, `imap_host`, `imap_port`, `imap_user`, `imap_password`, `imap_tls` |
| `twitter` | `tool_configs.twitter` (singleton, **merge into `social_x` is planned**) | Settings → Tool Configs → Twitter | `api_key`, `api_secret`, `access_token`, `access_token_secret`, `bearer_token` |
| `media_post` (`x`) | `tool_configs.social_x.config.accounts[]` (multi-account) | Settings → X (Twitter) — accounts | per account: `account_id`, `label`, `api_key`, `api_secret`, `access_token`, `access_token_secret`, `bearer_token` |
| `media_post` (`linkedin`) | `tool_configs.social_linkedin.config.accounts[]` (multi-account) | Settings → LinkedIn — accounts | per account: `account_id`, `label`, `client_id`, `client_secret`, `access_token`, `person_urn`, `organization_urn` |
| `media_post` (`instagram`) | `tool_configs.social_instagram.config.accounts[]` (multi-account) | Settings → Instagram — accounts | per account: `account_id`, `label`, `access_token`, `ig_user_id`, `fb_page_id` |
| `media_post` (`facebook`) | `tool_configs.social_facebook.config.accounts[]` (multi-account) | Settings → Facebook — accounts | per account: `account_id`, `label`, `page_access_token`, `page_id`, `app_id`, `app_secret` |
| `postiz` | `tool_configs.postiz` (singleton) | Settings → Tool Configs → Postiz | `api_url`, `api_key` |
| `trustless_otc` | `tool_configs.trustless_otc` (singleton) | Settings → Tool Configs → TrustlessOTC | `api_base_url`, `api_key` |
| `trading` | `tool_configs.trading` (policy; private keys live in env) | Settings → Tool Configs → Trading | policy: `max_tx_usd`, `allowed_chains`, `confirmation_mode`, `gas_multiplier`, `slippage_bps`. Hot-wallet keys: `TRADING_PRIVATE_KEYS` env (comma-separated). |
| `image_generate` | env vars (no DB row today) | `.env` | `IMAGE_GEN_API_URL`, `IMAGE_GEN_API_KEY` |
| `video_generate` | env var (no DB row today) | `.env` | `REMOTION_API_URL` (defaults to `http://bob-remotion:3020`) |
| `audio_generate` | `tool_configs.audio_generate` (per-script settings) | Settings → Tool Configs → Audio Generate | per-script keys (`script`, model paths, etc.) |
| `comfyui` | `tool_configs.comfyui` (server URL/auth, optional) | Settings → Tool Configs → ComfyUI | `server_url`, optional auth |

### How multi-account resolution works

1. Lab admin adds one or more accounts to a `social_<platform>` config via the Settings UI. Each account gets a generated `account_id` and a human-readable `label`.
2. The agent receives a tool grant such as `media_post:x`. At call time, the agent passes `account_id` (or first runs `action=list_accounts` to discover them).
3. `media_post` ([tool_social.py:89](control-plane/app/services/tools/tool_social.py#L89)) loads the matching account from the DB and forwards the credentials to the platform publisher. The agent never sees the raw credentials.

Sensitive values are masked in all API responses; the `PUT /tool-configs/<type>` and per-account `PATCH` endpoints preserve a masked value back to whatever the DB currently holds.

### Multi-user notes

The control plane today is **single-admin** — one shared-secret JWT, no `users` table. When a real users table lands, every multi-account row will gain a `user_id` field and the routes will enforce per-user ownership (a user only sees and uses their own accounts). The schema is shaped to make that addition a small migration, not a rewrite.
