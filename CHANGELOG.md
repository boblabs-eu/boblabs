# Changelog

All notable changes to Bob Labs are documented here.

This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.12.0] — 2026-06-15 — Real Hermes agents + Claude CLI provider

The biggest release since `0.10.0`. Two new top-level capabilities —
real Nous Hermes agents as a per-agent backend, and a Claude CLI
provider that turns a Claude Max subscription into a first-class
model source for any lab — plus a Contact Finder for the prospecting
blueprint and in-browser file editing. Two additive Alembic
migrations (`0012`, `0013`); deploy with `alembic upgrade head`.

### Added

- **Hermes agent backend** ([hermes-adapter/](hermes-adapter/),
  [docs/AGENTS_AND_ORCHESTRATION.md](docs/AGENTS_AND_ORCHESTRATION.md)).
  Each library agent can now run as **native** (Bob orchestrates a
  chosen model directly, the existing behavior) or **hermes** — a
  real instance of [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-function-calling)
  inside a dedicated container with its own persistent memory volume
  and tool layer. The new `0013_agent_backend` migration adds a
  `backend` column to `ai_agents` (default `native`); selector
  surfaces in the agent edit dialog. Control-plane spins the
  container on demand via docker-socket-proxy, serializes per-key
  calls, and reuses the lab's chosen model (`anthropic` / `ollama` /
  `openai` / `xai` / `groq` / `deepseek` resolved through Hermes'
  own provider matrix). Containers persist `~/.hermes` so memory,
  skills, and sessions survive restarts. Env knobs:
  `HERMES_IMAGE`, `HERMES_DEFAULT_TIMEOUT_SEC`, `HERMES_MEM_MB`,
  `HERMES_CPUS`.
- **Claude CLI model provider** (`claude-cli/`, [docs/CLAUDE_CLI.md](docs/CLAUDE_CLI.md)).
  Claude Code CLI runs on GPU servers in a Docker sidecar behind an
  OpenAI-compatible wrapper, authenticated with a `claude setup-token`
  OAuth token (Max subscription, no API credits). Integrated exactly
  like Ollama: the bob agent probes the wrapper and reports its models
  over the websocket (`claude_cli_models`), the control plane
  auto-creates a `claude_cli-<agent>` provider (pending admin
  approval) and syncs the models, and `LabDispatcher` routes inference
  through the existing `OpenAICompatibleProvider`. Model identifiers
  are namespaced `claude-cli:<id>` (e.g. `claude-cli:opus`) so they
  are visibly distinct from Anthropic API models everywhere in the
  UI. The model list is `.env`-driven (`CLAUDE_CLI_MODELS`, default
  `haiku,opus,sonnet`). v1 is text-only at the OpenAI layer — the lab drives
  tools via the `<tool_call>` text protocol, and any native `tool_use` the model
  emits is recovered into that text form.
- **In-browser editing of workspace text files.** The lab file viewer
  now has an Edit/Save flow for text/md/json/csv files
  (`PUT /labs/{id}/output-files/content`, EDIT-permission gated,
  512 KB cap, path-traversal safe). Truncated (large) files are
  read-only to avoid clobbering the dropped tail.
- **Contact Finder agent (Datagouv Prospecting blueprint).** A 4th agent runs
  between the Researcher and Copywriter and enriches each prospect with a
  PUBLISHED public contact email scraped from the company's official website
  (`web_search` + `web_extract`, never invented), adding `email`/`website`
  columns to `output/prospects.csv`; the Copywriter then pre-fills the draft
  `to:` when an email was found (empty + operator note otherwise). Company
  discovery stays strictly on `gouv_data_fr` — web access is scoped to the
  Contact Finder reading official sites only.

### Fixed

- **Stop on a paused lab left it stuck on "paused" (no Reset button).** The
  runner's top-of-loop pause gate didn't re-check the stop flag after waking, so
  `Pause` → `Stop` ran one more full iteration before exiting; when that outlasted
  `stop()`'s 30s timeout the `/stop` route returned while the DB still said
  `paused`, and the UI offers Reset only for `completed`/`failed`. The gate now
  terminalizes immediately on stop (matching the PauseAction/CRON gates), so Stop
  reliably moves a paused lab to `completed` and Reset becomes available.
- **Lab tool calls returning structured JSON crashed the run.** Tool
  outputs that are dicts (e.g. the `gouv_data_fr` tool) were stored with
  `output[:2000]`, and slicing a dict raises `KeyError: slice(None, 2000,
  None)`, aborting the lab. Outputs are now JSON-encoded before
  truncation (`_tool_output_preview`) across the runner, scheduler, and
  orchestrator streaming paths.
- **Edited workspace input files reverted on every run.** Lab
  `context_files` (e.g. `icp_brief.md`) were re-materialized from the DB
  over the on-disk copy each run, discarding user edits. They are now
  seeded only when missing — the workspace copy is the durable working
  copy; the DB keeps the blueprint default for reset/duplicate/export.
- **Claude CLI wrapper broke lab tool use.** The wrapper appended `"Respond
  with plain text only. Do not attempt to use tools."` to every system prompt.
  But a lab's prompt teaches the model the platform's `<tool_call>` TEXT
  protocol and asks it to call tools like `gouv_data_fr` — so that directive
  directly contradicted the task. The model, unable to tell native Claude tools
  from the lab's text protocol, either **refused to act** ("tool access is not
  available in this turn", "RUN STAYS STOPPED") or **flailed into a native
  `tool_use`** that blew the `--max-turns 1` one-shot (`error_max_turns` →
  502). The wrapper now passes the caller's system prompt through **verbatim**
  and disables native tools purely at the CLI level: `--tools ""` (built-ins,
  overridable via `CLAUDE_CLI_TOOLS`) and `--strict-mcp-config` (ambient MCP),
  leaving the lab's text protocol intact. Finally — because opus is trained
  toward native function-calling and on large, tool-heavy prompts will still
  *occasionally* emit a native `tool_use` despite `--tools ""` (server-flag
  dependent, so it reproduces on the deployed account but not on every machine)
  — the wrapper now reads the **streamed** output and **converts any native
  `tool_use` block into the lab's `<tool_call>` text**. With no native tools
  defined the model names the tool from the prompt (the lab's own `file_read` /
  `gouv_data_fr` / …), so the recovered call is faithful, both response shapes
  work, and `error_max_turns` is no longer fatal. (Also removed a stale
  `--disallowedTools MultiEdit` denylist
  that errored with `Permission deny rule ... matches no known tool`.) Upstream
  provider error **bodies** now surface in a lab's failure reason instead of a
  bare `502`.

### Changed

- **Docs:** `CLAUDE_CLI.md` + `AGENTS_AND_ORCHESTRATION.md` now describe the
  native-`tool_use` recovery (the wrapper converts it to `<tool_call>` text)
  instead of the old "tools accepted and ignored / never returns tool_calls".
- **Datagouv prospecting blueprint is now target-driven and
  offer-branded.** The Target Definer derives the ICP from an explicit
  `target_customer` (validated against the Annuaire des Entreprises)
  instead of copying the seller's own NAF, and the Copywriter pitches the
  brief's `offer` for `sender_company` instead of a hardcoded product.

### Schema migrations

| Revision | What it does |
|---|---|
| `0012_mcp_servers` | MCP server definitions table (admin-managed registry of external MCP endpoints labs can attach to) |
| `0013_agent_backend` | Adds `ai_agents.backend` column (default `native`); allows opting an agent into the Hermes runtime |

### Notes

- All four components aligned at **0.12.0**.
- Run `alembic upgrade head` before starting the new control-plane.
  Both migrations are additive (new tables / new column with default) —
  no data conversion, expected downtime ~30 s.
- `claude-cli/` and `hermes-adapter/` ship as new top-level directories.
  Neither needs the bob-manager docker-compose stack to be brought up
  at the root: claude-cli has its own per-server `claude-cli/docker-compose.yml`,
  and hermes-adapter is built locally and launched per-agent by the
  control plane.
- OpenAPI artifact at [docs/openapi.json](docs/openapi.json) reflects
  the new `claude_cli` provider type + Hermes routes (`/library-agents/{id}/hermes/{activate,deactivate,status}`).

[0.12.0]: https://github.com/boblabs-eu/boblabs/releases/tag/v0.12.0

## [0.11.1] — 2026-06-09 — Security hardening: metrics auth + container user

Patch release closing two CSO findings against 0.11.0. No schema
migrations, no deploy changes beyond rebuilding containers.

### Security

- **Auth required on `/api/v1/metrics/*`** (CSO #1, #2). The router
  was previously unauthenticated, so the cached agent-metrics payload
  (every GPU server's hostname, hardware inventory, CPU/GPU usage
  history, disk mounts, network throughput) was world-readable
  through nginx. Now gated by `require_infra_access`, mirroring
  `commands.py` / `servers.py`. **If you scraped `/metrics`
  unauthenticated, update your client to attach an access token with
  the `infra` scope or admin auth.**
- **Non-root container user** in every shipped Dockerfile
  (control-plane, agent, sandbox, remotion-api, all 7 GPU service
  images). Defense-in-depth: a process escape no longer lands as
  root inside the container.

### Added

- `control-plane/tests/regression/test_cso_2026_06_metrics_auth.py` —
  asserts the metrics router carries the auth dependency on every
  endpoint.
- `control-plane/tests/regression/test_cso_2026_06_dockerfile_user.py` —
  asserts each shipped Dockerfile declares a non-root `USER`.

### Notes

- All four components aligned at **0.11.1**.
- OpenAPI artifact regenerated — the metrics endpoints now carry a
  `HTTPBearer` security requirement in `docs/openapi.json`.

[0.11.1]: https://github.com/boblabs-eu/boblabs/releases/tag/v0.11.1

## [0.11.0] — 2026-06-07 — v1.0 prep: CI, versioning, OpenAPI commitment

No schema migrations, no runtime behavior changes. This release is
**process maturity for the upcoming v1.0** — getting the project's
governance and gate infrastructure to where a public 1.0 commitment
can be made honestly. Sit on `0.11.x` for 4–6 weeks of public burn-in
(real-world issues filed, fixes shipped) before tagging v1.0.

### Added

- **CI on every PR** — [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs
  five jobs in parallel: ruff lint, ruff format check, OpenAPI spec
  drift detection, `make test` (pytest), frontend Jest tests, and
  `docker compose config` + image build smoke. End-to-end ~6 min.
- **Ruff toolchain** — [`pyproject.toml`](pyproject.toml) configures
  `ruff check` (E/F/I/B/W rules) + `ruff format` (black-compatible)
  as the single source of truth for Python lint + style. The
  baseline commit ran `ruff check --fix` and `ruff format` across
  the entire codebase; no behavior changes, just consistency.
- **OpenAPI spec committed** — [`docs/openapi.json`](docs/openapi.json) is
  now the canonical public-API contract. Generated via
  [`scripts/export_openapi.py`](scripts/export_openapi.py); drift-checked
  in CI via [`scripts/check_openapi_drift.sh`](scripts/check_openapi_drift.sh).
  Clients can read the contract without booting the stack.
- **Versioning policy** — new [`VERSIONING.md`](VERSIONING.md) defines
  what's public (REST `/api/v1/*`, consumer-app HMAC envelope, lab
  blueprint shape, WebSocket events, env vars, schema migrations)
  vs. internal (module layout, repositories, frontend components).
  Includes the deprecation policy and SemVer mapping that v1.0 will
  commit to.
- **Upgrade guide** — new [`UPGRADE.md`](UPGRADE.md) with the generic
  upgrade flow + per-version notes. Documents the 0.10.0 trading-
  precision migration as one-way.
- **Issue + PR templates** — [`.github/ISSUE_TEMPLATE/bug_report.yml`](.github/ISSUE_TEMPLATE/bug_report.yml),
  [`.github/ISSUE_TEMPLATE/feature_request.yml`](.github/ISSUE_TEMPLATE/feature_request.yml),
  [`.github/ISSUE_TEMPLATE/config.yml`](.github/ISSUE_TEMPLATE/config.yml) (blank issues
  disabled, security routed to SECURITY.md, questions routed to
  Discussions), and [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md).

### Changed

- **Codebase formatted** — single `ruff format` pass across all
  Python sources outside `migrations/versions/`. Pure cosmetic;
  no behavior changes.
- **`lab_scheduler._recover_stuck_labs`** now binds `now =
  datetime.now(timezone.utc)` at the top of the function (was
  silently `NameError`-prone in the paused-with-cron recovery
  branch).

### Fixed

- Three pre-existing test failures that had been quietly red since
  the 0011 trading-precision migration (test_session7 path math,
  test_wave4 ensure_sandbox assertion, test_cross_tenant
  TradingPosition field names) now pass against the post-migration
  ORM.

### Notes

- Versions of all four components (agent, control-plane, frontend,
  remotion-api) aligned at **0.11.0**.
- The control-plane FastAPI app now sets `version=__version__`
  consistently — visible at `GET /api/v1/health` and
  `GET /openapi.json` (info.version).
- Still pre-1.0 — SemVer stability for the public API will land
  with **v1.0.0** after public burn-in proves the contract.

[0.11.0]: https://github.com/boblabs-eu/boblabs/releases/tag/v0.11.0

## [0.10.0] — 2026-06-07 — Security sweep + schema evolution + repo hardening

Second public release. Most of this is the **Phase 5 audit closeout**: a
month of follow-up work after `0.9.0` shipped, covering security gates
across the auth + ACL surface, the data layer (pagination, N+1, cross-
tenant isolation), the sandbox lifecycle, the GPU services, and trading
amount precision. 8 new Alembic migrations evolve the schema; deploy
with `alembic upgrade head` before starting the new code.

### Added

- **Markdown-rendered blog posts** — `react-markdown` + `remark-gfm`
  replace the naive newline-to-paragraph renderer; GFM tables, code
  blocks, blockquotes, headings, and inline links now render correctly
  on `/blog/<slug>`.
- **Multi-domain hosting** — control-plane and `bob-ui` recognize
  alternative root domains (e.g. `cryptobob.<tld>`) and tailor the
  surfaced nav per domain.
- **Admin Outreach approval queue ACLs** — outreach routes now check
  per-lab ACL in addition to the global admin gate, so multi-tenant
  deployments don't leak drafts across labs.

### Changed

- **Repository layer sweep** — every list endpoint now paginates
  (`_paginate.py` helper), every join is N+1-audited, and every cross-
  tenant query asserts owner / ACL membership (`_sanitize.py`). The
  legacy unbounded list-all paths are gone.
- **Workflow execution** — `execute` now requires `EDIT` on the
  workflow (was previously only `VIEW`); workflow step ACL shape
  unified across consumer-app / showroom / agent-instance labs.
- **Trading precision** — historical decimal-string amounts migrated
  to wei-integer + per-asset decimals (`0011_trading_precision`). The
  old float-based comparisons were causing 1-wei dust drift on
  reconciliation.
- **Documentation** — public `/docs` migrated to `react-markdown` v10
  (block code now routes through the `pre` component instead of the
  removed `inline` flag).

### Security

- **Per-workflow ACL** with execute → EDIT gate; definition JSONB
  synced atomically.
- **AI provider auto-discovery** now lands in a `pending` state and
  requires admin approval before any prompt traffic flows through.
- **Bearer tokens hashed at rest** (Argon2id); constant-time admin
  login compare; query logs scrub bearer/cookie headers.
- **WebSocket `/ws/client`** requires a JWT; broadcasts are audience-
  scoped; terminal session ownership enforced server-side.
- **Atomic runner reservation** — race-free claim on the lab → runner
  binding; pause cold-path guards against terminal-session reuse.
- **`require_admin` on `/admin/consumer-apps/*`** — no longer falls
  through on a missing role claim.
- **Segment-aware path containment** — every artifact / upload /
  workspace path goes through the same containment helper; traversal
  via `..` segments rejected before disk touch.
- **`direct_cmd_exec` removed** — all shell paths now route through
  the sandbox HTTP API with the command allow-list.

### Fixed

- Admin login at `/admin` now also authenticates the global session
  (was issuing a panel-only token).
- Sandbox lifecycle — terminal-session cleanup, hub pending-future
  leak, ungraceful kill on lab pause (R01, R02, R04, R07-R11).
- GPU service hardening — STT pre-reads the audio buffer before
  hand-off; Coqui falls back to CPU when the GPU pool is saturated;
  GPU semaphores keyed by `(host, port)` so per-GPU concurrency is
  honored across the fleet.

### Schema migrations

| Revision | What it does |
|---|---|
| `0004_workflows_acl` | Adds `owner_id`, `editor_ids`, `viewer_ids` to workflows |
| `0005_ai_providers_pending` | New `pending` state on auto-discovered AI providers |
| `0006_token_hashes` | Migrates access-token storage from plaintext to Argon2id hashes |
| `0007_portfolio_snapshots_pk` | Fixes the composite PK on `portfolio_snapshots` |
| `0008_lab_web3_default` | Adds `web3_enabled` default to lab settings |
| `0009_workflow_step_acl_shape` | Unifies workflow-step ACL JSONB shape across lab kinds |
| `0010_lab_loop_type_check` | `CHECK` constraint matching the `Literal` alias on `lab.loop_type` |
| `0011_trading_precision` | Wei-integer amount columns + per-asset decimals |

### Internal / tests

- Cluster A-R + Wave 4 regression suites — pytest harness, permission
  unit tests, service-layer tests, repository tests. See
  [docs/TESTING.md](docs/TESTING.md).
- Source-introspection regression sweeps for the Phase 5 invariants
  (bob-manager-internal — not shipped public; the public surface is
  covered by the cluster suites).

### Notes

- Versions of all four components (agent, control-plane, frontend,
  remotion-api) are aligned at **0.10.0**.
- This release contains schema migrations. Run
  `alembic upgrade head` against your `bob-db` before starting the new
  control-plane. Roll-forward only; downgrades not maintained.
- Still pre-1.0 — SemVer stability for the public API will land at
  `1.0.0` after a few weeks of public burn-in.

[0.10.0]: https://github.com/boblabs-eu/boblabs/releases/tag/v0.10.0

## [0.9.0] — 2026-05-20 — Initial open-source release

This is the first public cut of Bob Labs as
[`boblabs-eu/boblabs`](https://github.com/boblabs-eu/boblabs). The
platform has been running internally with 190+ labs and two consumer
apps; this release exposes the core to anyone who wants to self-host
an agent platform on their own GPUs.

### Added

- Multi-agent **lab runner** with pluggable loop strategies
  (Plan-Execute, Critique-Refine, Round-Robin, solo agent, custom).
- **40 sandboxed built-in tools** across reasoning, memory, file I/O,
  code execution, web, media generation, RAG, database, diagrams,
  comms, data (incl. data.gouv.fr), web3, and ops. See
  [docs/TOOLS_AND_SANDBOX.md](docs/TOOLS_AND_SANDBOX.md).
- **Private RAG** (Qdrant + LightRAG) with per-collection ACLs and
  PDF/Markdown/HTML/URL ingest.
- **GPU dispatcher** across N hosts — auto-discovery of agents,
  least-loaded routing, retry on failure, hot-swap on Ollama, live
  load-balancer feed.
- **Sandboxed code/shell execution** per-lab via docker-socket-proxy +
  command allow-list + resource caps.
- **Anti-loop detector** catching semantic repetition and tool-call
  loops, with automatic memory sweep and pause/recovery.
- **Skill files convention** (`templates/skills/<name>.md`) —
  context-file entries on a lab blueprint are materialized to the
  agent's workspace at boot, agents `file_read` them on demand.
- **Consumer-app HMAC channel** (`/api/v1/internal/apps/*`) — admin-
  managed app key registry, per-app RAG/agents/lab namespaces,
  callback delivery, full integration contract documented in
  [docs/CONSUMER_APPS.md](docs/CONSUMER_APPS.md).
- **JWT auth + per-resource ACL** (`owner` / `editors` / `viewers`)
  on labs, projects, resources, RAG collections, wallets, with an
  admin panel for managing access tokens and trial requests.
- **Public `/live` page** with **opt-in visibility per lab** —
  private by default; owners or admins toggle via the Share modal or
  the new Admin → Labs tab.
- **Outreach approval queue** — agents draft cold emails into
  `output/drafts/*.md` with YAML frontmatter; humans approve / edit /
  reject / send via SMTP. No mail ever leaves the platform without a
  human click.
- **9 GPU microservices** (MusicGen, Bark, RVC, CoquiTTS, STT,
  LTX-Video, Wan-Video, Remotion, ComfyUI bridge), each in its own
  compose file, mix-and-match per host.
- **First-class adapters** for Ollama, vLLM, HuggingFace TGI, OpenAI,
  Anthropic, xAI, Groq, DeepSeek.
- **Real-time event bus** — every orchestrator decision, tool call,
  agent message broadcast over WebSocket.
- **Two-command deploy**: `cp .env.example .env && docker compose up
  -d --build`.

### Notes

- Versions of all four components (agent, control-plane, frontend,
  remotion-api) are aligned at **0.9.0**.
- We have not yet committed to SemVer stability for the public API —
  expect minor breaking changes before 1.0.0. Subscribe to the
  release feed to know when they happen.
- All 40 built-in tools pass the smoke gate. See
  [docs/TOOL_TEST_REPORT.md](docs/TOOL_TEST_REPORT.md) for the most
  recent run.
- See [CONTRIBUTING.md](CONTRIBUTING.md) for how to file issues, run
  the dev stack, and submit PRs.
- Security disclosures go to **support@boblabs.eu** — see
  [SECURITY.md](SECURITY.md).

[0.9.0]: https://github.com/boblabs-eu/boblabs/releases/tag/v0.9.0
