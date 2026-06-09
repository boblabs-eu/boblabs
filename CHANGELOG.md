# Changelog

All notable changes to Bob Labs are documented here.

This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
