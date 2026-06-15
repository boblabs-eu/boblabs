# Bob Labs — API Reference

**Base URL:** `http://localhost:8888/api/v1` (host port; container listens on `bob-api:8000`)
**Authentication:** JWT Bearer for operator endpoints, HMAC for `/internal/*` consumer-app endpoints (see [Authentication](#authentication))

---

## Authentication

Three authentication methods:

| Method | Endpoint / Mechanism | Use Case |
|--------|----------------------|----------|
| Admin login | `POST /public/admin-login` | Admin access via `ADMIN_SECRET` |
| Access token | `POST /public/validate-token` | User access via time-limited token |
| Consumer-app HMAC | `X-App-Id` + `X-App-Timestamp` + `X-App-Signature` headers on `/internal/apps/*` | Private consumer-app server-to-server channel. Per-app HMAC keys are managed in the `consumer_apps` table via bob-ui → Admin → Consumer Apps. Full contract in [CONSUMER_APPS.md](CONSUMER_APPS.md). |

Login methods return a JWT for use in `Authorization: Bearer <token>` headers.

**Agent auth:** Agents connect via WebSocket with `AGENT_SECRET` in the handshake.

---

## Root

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | No | API info |
| GET | `/health` | No | Health check |

---

## Auth (`/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/token` | No | Exchange shared secret for JWT |

---

## Servers (`/servers`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/servers` | Yes | List all registered servers |
| GET | `/servers/{server_id}` | Yes | Get server details |
| POST | `/servers` | Yes | Register a server manually |
| PUT | `/servers/{server_id}` | Yes | Update server config |
| DELETE | `/servers/{server_id}` | Yes | Remove server |
| GET | `/servers/{server_id}/metrics` | Yes | Cached agent metrics |
| GET | `/servers/{server_id}/processes` | Yes | Live process list |
| GET | `/servers/{server_id}/services` | Yes | Systemd services |
| GET | `/servers/{server_id}/crontabs` | Yes | Crontab entries |
| GET | `/servers/{server_id}/ports` | Yes | Open ports |
| GET | `/servers/{server_id}/firewall` | Yes | UFW firewall status |

---

## Commands (`/commands`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/commands/servers/{server_id}` | Yes | Execute command on server |
| POST | `/commands/batch` | Yes | Execute on multiple servers |
| GET | `/commands/servers/{server_id}/history` | Yes | Command history |

---

## Workflows (`/workflows`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/workflows` | Yes | List workflows |
| GET | `/workflows/{workflow_id}` | Yes | Get workflow |
| POST | `/workflows` | Yes | Create workflow |
| PUT | `/workflows/{workflow_id}` | Yes | Update workflow |
| DELETE | `/workflows/{workflow_id}` | Yes | Delete workflow |
| POST | `/workflows/{workflow_id}/execute` | Yes | Execute on servers |
| GET | `/workflows/{workflow_id}/executions` | Yes | Execution history |

---

## Projects (`/projects`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/projects` | Yes | List projects |
| POST | `/projects` | Yes | Create project |
| GET | `/projects/{project_id}` | ACL:VIEW | Get project |
| PUT | `/projects/{project_id}` | ACL:EDIT | Update project |
| DELETE | `/projects/{project_id}` | ACL:DELETE | Delete project |
| GET | `/projects/{project_id}/resources` | Yes | Linked resources |
| GET | `/projects/themes` | Yes | List themes with colors |
| POST | `/projects/themes/rename` | Yes | Rename theme globally |
| PUT | `/projects/themes/{name}/color` | Yes | Set theme color |

### Modules (`/projects/{project_id}/modules`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `.../modules` | Yes | List modules |
| POST | `.../modules` | Yes | Create module |
| PUT | `.../modules/{module_id}` | Yes | Update module |
| DELETE | `.../modules/{module_id}` | Yes | Delete module |
| GET | `.../modules/{module_id}/steps` | Yes | List steps |
| POST | `.../modules/{module_id}/steps` | Yes | Create step |
| PUT | `.../modules/{module_id}/steps/{step_id}` | Yes | Update step |
| DELETE | `.../modules/{module_id}/steps/{step_id}` | Yes | Delete step |
| GET | `.../modules/{module_id}/tasks` | Yes | List tasks |
| POST | `.../modules/{module_id}/tasks` | Yes | Create task |
| PUT | `.../modules/{module_id}/tasks/{task_id}` | Yes | Update task |
| DELETE | `.../modules/{module_id}/tasks/{task_id}` | Yes | Delete task |

---

## Resources (`/resources`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/resources` | Yes | List resources |
| POST | `/resources` | Yes | Create resource |
| GET | `/resources/{resource_id}` | ACL:VIEW | Get with linked projects |
| PUT | `/resources/{resource_id}` | ACL:EDIT | Update resource |
| DELETE | `/resources/{resource_id}` | ACL:DELETE | Delete resource |
| GET | `/resources/{resource_id}/projects` | Yes | Linked projects |
| POST | `/resources/{resource_id}/projects` | Yes | Link to project |
| DELETE | `/resources/{resource_id}/projects/{project_id}` | Yes | Unlink |

---

## Metrics (`/metrics`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/metrics` | Yes | All cached agent metrics |
| GET | `/metrics/{server_name}` | Yes | Metrics for one server |

---

## News (`/news`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/news/` | Yes | RSS feed articles (query: `category`) |
| GET | `/news/sources` | Yes | Configured feed sources |

---

## Web3 (`/web3`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/web3/prices` | Yes | Live BTC, ETH, BNB prices |
| GET | `/web3/portfolio` | Yes | Total portfolio value |
| GET | `/web3/settings` | Yes | Web3 settings |
| PUT | `/web3/settings` | Yes | Update settings |
| GET | `/web3/wallets` | Yes | List wallets |
| POST | `/web3/wallets` | Yes | Track a wallet |
| DELETE | `/web3/wallets/{wallet_id}` | Yes | Remove wallet |
| GET | `/web3/wallets/{wallet_id}/balances` | Yes | Wallet balances |
| GET | `/web3/wallets/{wallet_id}/transactions` | Yes | Transactions (query: `chain`) |
| GET | `/web3/portfolio/history` | Yes | Portfolio time-series |
| POST | `/web3/portfolio/snapshot` | Yes | Trigger snapshot |
| POST | `/web3/portfolio/cleanup` | Yes | Cleanup old snapshots |

---

## Orchestrator (`/orchestrator`)

### Settings

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/orchestrator/settings` | Yes | Get settings |
| PUT | `/orchestrator/settings` | Yes | Update settings |

### Providers

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/orchestrator/providers` | Yes | List providers |
| POST | `/orchestrator/providers` | Yes | Add provider |
| PUT | `/orchestrator/providers/{id}` | Yes | Update provider |
| DELETE | `/orchestrator/providers/{id}` | Yes | Delete provider |
| POST | `/orchestrator/providers/{id}/test` | Yes | Test connectivity |
| POST | `/orchestrator/providers/{id}/discover` | Yes | Discover models |

### Models

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/orchestrator/models` | Yes | List models (query: `provider_id`) |
| GET | `/orchestrator/models/unique` | Yes | Deduplicated models |
| GET | `/orchestrator/models/live` | Yes | Live models from providers |
| POST | `/orchestrator/models/sync` | Yes | Force-sync to DB |

### Agents (Global)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/orchestrator/agents` | Yes | List agents |
| POST | `/orchestrator/agents` | Yes | Create agent |
| PUT | `/orchestrator/agents/{id}` | Yes | Update agent |
| DELETE | `/orchestrator/agents/{id}` | Yes | Delete agent |

### Conversations

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/orchestrator/conversations` | Yes | List (query: `conv_status`) |
| POST | `/orchestrator/conversations` | Yes | Create |
| GET | `/orchestrator/conversations/{id}` | ACL:VIEW | Get |
| PUT | `/orchestrator/conversations/{id}` | ACL:EDIT | Update |
| DELETE | `/orchestrator/conversations/{id}` | ACL:DELETE | Delete |
| GET | `/orchestrator/conversations/{id}/messages` | ACL:VIEW | Get messages (query: `limit`) |
| POST | `/orchestrator/conversations/{id}/messages` | ACL:EDIT | Send message → SSE stream |

### LLM Events

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/orchestrator/llm-events` | Yes | Recent events |
| GET | `/orchestrator/llm-events/stats` | Yes | Aggregated stats |
| GET | `/orchestrator/llm-events/{id}` | Yes | Event with full I/O |

### Tasks & Activity

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/orchestrator/tasks` | Yes | List tasks |
| GET | `/orchestrator/activity` | Yes | Combined activity feed |

### Pipelines

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/orchestrator/pipelines` | Yes | Media pipelines with status |

---

## Labs (`/labs`)

### CRUD

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/labs` | Yes | List labs |
| POST | `/labs` | Yes | Create lab |
| GET | `/labs/{lab_id}` | Yes | Get lab |
| PATCH | `/labs/{lab_id}` | Yes | Update lab |
| DELETE | `/labs/{lab_id}` | Yes | Delete lab |
| POST | `/labs/{lab_id}/duplicate` | Yes | Duplicate with agents/tools |

### Blueprint (Import/Export)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/labs/{lab_id}/export` | Yes | Export as JSON blueprint |
| POST | `/labs/import` | Yes | Import from blueprint |

### Execution

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/labs/{lab_id}/run` | Yes | Start/resume |
| POST | `/labs/{lab_id}/reset` | Yes | Reset to fresh state |
| POST | `/labs/{lab_id}/pause` | Yes | Pause |
| POST | `/labs/{lab_id}/resume` | Yes | Resume |
| POST | `/labs/{lab_id}/stop` | Yes | Stop |
| POST | `/labs/{lab_id}/inject` | Yes | Inject user message |

### Agents

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/labs/{lab_id}/agents` | Yes | List lab agents |
| POST | `/labs/{lab_id}/agents` | Yes | Create agent |
| PATCH | `/labs/{lab_id}/agents/{id}` | Yes | Update agent |
| DELETE | `/labs/{lab_id}/agents/{id}` | Yes | Delete agent |

### Tools

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/labs/{lab_id}/tools` | Yes | List tools |
| POST | `/labs/{lab_id}/tools` | Yes | Create tool |
| PATCH | `/labs/{lab_id}/tools/{id}` | Yes | Update tool |
| DELETE | `/labs/{lab_id}/tools/{id}` | Yes | Delete tool |

### Messages & Memories

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/labs/{lab_id}/messages` | Yes | Messages (query: `iteration`) |
| GET | `/labs/{lab_id}/memories` | Yes | Memories (query: `scope`) |
| PATCH | `/labs/{lab_id}/memories/{id}` | Yes | Toggle memory visibility |

### Resources (File Uploads)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/labs/{lab_id}/resources` | Yes | List uploads |
| POST | `/labs/{lab_id}/resources` | Yes | Upload file |
| GET | `/labs/{lab_id}/resources/{id}/download` | Yes | Download file |
| DELETE | `/labs/{lab_id}/resources/{id}` | Yes | Delete file |
| GET | `/labs/{lab_id}/resources/{id}/content` | Yes | Preview content |

### Output Files

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/labs/{lab_id}/output-files` | Yes | List workspace files |
| GET | `/labs/{lab_id}/output-files/download` | Yes | Download file |
| GET | `/labs/{lab_id}/output-files/content` | Yes | Preview content |
| GET | `/labs/{lab_id}/output-files/history` | Yes | File history |

### RAG Access

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/labs/{lab_id}/rag-access` | Yes | List RAG access |
| POST | `/labs/{lab_id}/rag-access` | Yes | Grant collection access |
| PATCH | `/labs/{lab_id}/rag-access/{id}` | Yes | Update permissions |
| DELETE | `/labs/{lab_id}/rag-access/{id}` | Yes | Revoke access |

### Strategy & Library

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/labs/strategy-prompts/{loop_type}` | Yes | Default system prompt |
| GET | `/labs/agents/library` | Yes | All agents across labs |

---

## Tool Sets (`/tool-sets`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/tool-sets` | Yes | List |
| POST | `/tool-sets` | Yes | Create |
| GET | `/tool-sets/{id}` | Yes | Get |
| PATCH | `/tool-sets/{id}` | Yes | Update |
| DELETE | `/tool-sets/{id}` | Yes | Delete |
| POST | `/tool-sets/{id}/duplicate` | Yes | Duplicate |

---

## Prompt Templates (`/prompt-templates`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/prompt-templates` | Yes | List |
| POST | `/prompt-templates` | Yes | Create |
| GET | `/prompt-templates/{id}` | Yes | Get |
| PATCH | `/prompt-templates/{id}` | Yes | Update |
| DELETE | `/prompt-templates/{id}` | Yes | Delete |
| POST | `/prompt-templates/{id}/duplicate` | Yes | Duplicate |

---

## Library Agents (`/library-agents`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/library-agents` | Yes | List |
| POST | `/library-agents` | Yes | Create |
| GET | `/library-agents/{id}` | Yes | Get |
| PATCH | `/library-agents/{id}` | Yes | Update |
| DELETE | `/library-agents/{id}` | Yes | Delete |
| POST | `/library-agents/{id}/duplicate` | Yes | Duplicate |

### Hermes backend lifecycle

Container lifecycle for `backend: hermes` agents — see [HERMES.md](HERMES.md).
`{id}` accepts a library-agent id or a standalone lab-agent id.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/library-agents/{id}/hermes/activate` | Admin | Pop/start the agent's Hermes container, wait for health |
| POST | `/library-agents/{id}/hermes/deactivate` | Admin | Stop the container (memory volume kept) |
| DELETE | `/library-agents/{id}/hermes/container` | Admin | Remove the container (memory volume kept) |
| GET | `/library-agents/{id}/hermes/status` | Admin | `{image_configured, running, healthy, url, backend}` |

---

## LLM Gateway (`/llm-gateway`)

Internal OpenAI-compatible surface used by Hermes containers — every call is
routed through the LabDispatcher (load balancing, concurrency slots, LLM-event
feed). Auth: `Authorization: Bearer <AGENT_SECRET>` (machine channel, not JWT).
`{tag}` is the calling agent's id (used for feed attribution).

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/llm-gateway/{tag}/v1/models` | Agent secret | OpenAI-style model listing (available identifiers) |
| POST | `/llm-gateway/{tag}/v1/chat/completions` | Agent secret | Chat completion (tools + SSE streaming supported), dispatched via the load balancer |

---

## MCP Servers (`/mcp`)

External Model Context Protocol servers whose tools are exposed to agents as
`mcp__<slug>__<tool>` (or whole-server via the `mcp:<slug>` token).

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/mcp/catalog` | Admin | Curated presets (Stripe, data.gouv.fr, GitHub, …) |
| GET | `/mcp/servers` | Admin | List configured MCP servers |
| POST | `/mcp/servers` | Admin | Enable a catalog entry or add a custom MCP |
| PATCH | `/mcp/servers/{id}` | Admin | Toggle `enabled`, edit credentials |
| DELETE | `/mcp/servers/{id}` | Admin | Remove (tools unregistered on re-sync) |
| POST | `/mcp/servers/{id}/test` | Admin | Health check + preview of exposed tools |

---

## Cron Jobs (`/cron-jobs`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/cron-jobs` | Yes | List |
| POST | `/cron-jobs` | Yes | Create |
| GET | `/cron-jobs/{id}` | Yes | Get |
| PATCH | `/cron-jobs/{id}` | Yes | Update |
| DELETE | `/cron-jobs/{id}` | Yes | Delete |
| POST | `/cron-jobs/{id}/duplicate` | Yes | Duplicate |
| GET | `/cron-jobs/{id}/labs` | Yes | Labs using this job |

---

## RAG (`/rag`)

### Collections

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/rag/collections` | Yes | List collections |
| POST | `/rag/collections` | Yes | Create collection |
| GET | `/rag/collections/{id}` | Yes | Get collection |
| PATCH | `/rag/collections/{id}` | Yes | Update collection |
| DELETE | `/rag/collections/{id}` | Yes | Delete collection |

### Documents

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/rag/collections/{id}/documents` | Yes | List documents |
| POST | `/rag/collections/{id}/documents` | Yes | Upload document |
| POST | `/rag/collections/{id}/documents/from-url` | Yes | Ingest from URL |
| DELETE | `/rag/collections/{id}/documents/{doc_id}` | Yes | Delete document |
| POST | `/rag/collections/{id}/documents/{doc_id}/reingest` | Yes | Re-ingest document |
| POST | `/rag/collections/{id}/documents/reingest-all` | Yes | Re-ingest all |

### Search

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/rag/search` | Yes | Search collections |

---

## Access Tokens (`/access-tokens`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/access-tokens` | Admin | List tokens |
| POST | `/access-tokens` | Admin | Generate token |
| DELETE | `/access-tokens/{id}` | Admin | Revoke token |
| GET | `/access-tokens/trial-requests` | Admin | List trial requests |
| PATCH | `/access-tokens/trial-requests/{id}` | Admin | Update trial status |
| GET | `/access-tokens/quote-requests` | Admin | List quote requests |
| PATCH | `/access-tokens/quote-requests/{id}` | Admin | Update quote status |
| PATCH | `/access-tokens/acl` | Admin | Update ACL on any resource |
| GET | `/access-tokens/platform/infra-access` | Admin | Infra whitelist |
| PUT | `/access-tokens/platform/infra-access` | Admin | Update whitelist |
| GET | `/access-tokens/blog-tokens` | Admin | List blog tokens |
| POST | `/access-tokens/blog-tokens` | Admin | Create blog token |
| DELETE | `/access-tokens/blog-tokens/{id}` | Admin | Revoke blog token |

---

## Tool Configs (`/tool-configs`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/tool-configs` | Yes | List configs |
| GET | `/tool-configs/schema` | Yes | Config schemas |
| GET | `/tool-configs/{tool_type}` | Yes | Get config |
| PUT | `/tool-configs/{tool_type}` | Yes | Set config |
| DELETE | `/tool-configs/{tool_type}` | Yes | Delete config |

---

## Public (`/public`)

No authentication required.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/public/trial-request` | Submit trial request |
| POST | `/public/quote-request` | Submit quote request |
| POST | `/public/validate-token` | Validate access token → JWT |
| POST | `/public/admin-login` | Admin login |
| GET | `/public/blog` | List blog posts |
| GET | `/public/blog/{post_id}` | Get blog post |
| POST | `/public/blog` | Create blog post (admin/blog token) |
| GET | `/public/live/labs` | List labs (public live page) |
| GET | `/public/live/labs/{lab_id}` | Get lab (public live page) |
| GET | `/public/live/labs/{lab_id}/messages` | Recent messages (sanitized) |

---

## Outreach (`/outreach`)

Drafts produced by lab agents that are queued for human review before sending
(email outreach, social drafts).

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/outreach/drafts` | Yes | List pending drafts across all labs |
| GET | `/outreach/drafts/{lab_id}/{filename}` | Yes | Read one draft |
| PATCH | `/outreach/drafts/{lab_id}/{filename}` | Yes | Edit a draft in place |
| POST | `/outreach/drafts/{lab_id}/{filename}/reject` | Yes | Mark draft rejected |
| POST | `/outreach/drafts/{lab_id}/{filename}/send` | Yes | Send via the configured channel |

---

## Admin Logs (`/admin/logs`)

Observability over recent API and lab-loop activity. Admin-only.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/admin/logs/requests` | Admin | Paged HTTP request log with filters |
| GET | `/admin/logs/facets` | Admin | Distinct values for filter dropdowns |
| GET | `/admin/logs/metrics` | Admin | Aggregated request metrics over a time range |
| GET | `/admin/logs/lab-loops` | Admin | Recent lab-loop iterations (start/end, status, agent) |
| GET | `/admin/logs/tasks` | Admin | Background task history (scheduler, dispatcher) |

---

## Admin — Consumer Apps (`/admin/consumer-apps`)

CRUD over the `consumer_apps` registry. Plain HMAC secret returned **once**
at creation, never again — admins paste it into the consumer app's `.env`
as `BOB_APP_SECRET`. Admin JWT required.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/consumer-apps` | List registered consumer apps (no secrets in response) |
| POST | `/admin/consumer-apps` | Register a new consumer app; returns the one-time HMAC secret |
| DELETE | `/admin/consumer-apps/{id}` | Revoke a consumer app |

---

## Internal — Apps (`/internal/apps`)

> **HMAC-only.** Each request must carry `X-App-Id`, `X-App-Timestamp`
> (unix seconds) and `X-App-Signature` (`hmac_sha256(secret, "<ts>.<body>")`).
> The matching HMAC key is looked up in the `consumer_apps` table by
> `app_id`. Replay window: 300 s. Unknown / revoked / bad-sig collapse to
> 401 to prevent app-id enumeration.
>
> Outgoing callbacks from bob-api back to the consumer app's webhook URL
> are signed with the same key and carry the same headers. See
> [CONSUMER_APPS.md](CONSUMER_APPS.md) for the full contract.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/internal/apps/import_lab` | Idempotent import of a lab blueprint. |
| POST | `/internal/apps/run` | Direct ComfyUI texture-mixing dispatch. Result posted to `callback_url`. |
| POST | `/internal/apps/run_lab` | Clone a template lab, seed context files, run agents, copy artifacts, post callback. |
| POST | `/internal/apps/run_flux_text2img` | ComfyUI Flux.1-Dev text-to-image. |
| POST | `/internal/apps/run_ltx_image2video` | ComfyUI LTX-2.3 image-to-video. |
| POST | `/internal/apps/run_ffmpeg_op` | Local ffmpeg subprocess (extract last frame, concat). |
| POST | `/internal/apps/transcribe` | STT dispatcher proxy (audio → text, queued). |
| POST | `/internal/apps/llm_complete` | One-shot load-balanced LLM chat completion. |

---

## WebSocket

| Endpoint | Auth | Description |
|----------|------|-------------|
| `ws://host:port/ws/agent` | AGENT_SECRET | Agent ↔ control plane |
| `ws://host:port/ws/client` | JWT | Frontend real-time updates |

---

## Related Documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — System architecture
- [CONFIGURATION.md](CONFIGURATION.md) — Environment variables
- [ACCESS_CONTROL.md](ACCESS_CONTROL.md) — ACL & permissions
- [INSTALL_PROD.md](INSTALL_PROD.md) — Deployment guide
