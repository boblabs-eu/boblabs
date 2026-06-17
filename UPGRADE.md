# Upgrade Guide

This file documents the canonical upgrade flow for self-hosted Bob Labs
deployments, plus per-version notes for any release that needs special
handling (schema migrations, env-var changes, breaking shifts).

Releases are tagged on GitHub as `v<X.Y.Z>` and tracked in
[CHANGELOG.md](CHANGELOG.md). The version contract is defined in
[VERSIONING.md](VERSIONING.md).

---

## Generic upgrade flow

This works for **every** release. The per-version sections below add
any extra steps specific to that bump.

```bash
# 1. Pull the new code
cd /path/to/boblabs
git fetch origin
git checkout v<X.Y.Z>           # the release tag

# 2. Back up the database first — always
docker exec bob-db pg_dump -U bobmanager bobmanager \
    > backup-$(date +%Y%m%d-%H%M).sql

# 3. Stop services
docker compose down

# 4. Rebuild + apply migrations + start
./deploy-prod.sh
# deploy-prod.sh runs `alembic upgrade head` against bob-db automatically.
# Skip with --skip-migrations if you've already applied them out of band.

# 5. Verify the API is healthy
curl -s http://localhost:8888/api/v1/health | jq .
# expected: {"status": "ok", "version": "<X.Y.Z>", ...}
```

**Expected downtime**: ~10–30 seconds for restart + migration window,
unless a per-version section below says otherwise.

---

## Rollback policy

Bob Labs schema migrations are **forward-only**. `alembic downgrade`
is not maintained and may not work cleanly across versions.

To roll back to a previous version:

```bash
# 1. Stop services
docker compose down

# 2. Restore the pre-upgrade backup
docker compose up -d bob-db
docker exec -i bob-db psql -U bobmanager bobmanager < backup-<date>.sql

# 3. Check out the previous tag and restart
git checkout v<previous-X.Y.Z>
./deploy-prod.sh
```

Always test the rollback path against staging before relying on it in
production. The single rule: **never skip step 2 of the upgrade flow.**

---

## Per-version notes

Most recent first.

### 0.12.6 → 0.12.7

**Theme**: Frontend fix — the Agents console no longer freezes on
`COMPLETED` after injecting a message into a completed instance.

Root cause: the instances-list polling effect was gated on
`some(i => i.status === 'running' || 'paused')`, which is
chicken-and-egg: with no other active instance, polling never
started, so the just-injected instance's status badge couldn't
refresh. Verified via DevTools Network — on an environment where
another instance happened to be running, the global poller ran
incidentally and masked the bug.

Two changes in `frontend/src/components/agents/AgentsView.js`:

- `handleInjectInstance` now refreshes the instance list (not just
  the per-instance messages), so the status badge picks up the
  server-side flip from `completed` to `running` within ~200 ms.
- The per-instance polling effect drops the
  `status === running/paused` gate. Polls every 3 s whenever an
  instance is open, refreshing both the per-instance data and the
  instances list.

- **Schema migrations**: none.
- **Env vars**: no changes.
- **Downtime**: ~10 s for the restart.
- **Action**: `git pull && bash deploy-prod.sh` — rebuilds `bob-ui`.

### 0.12.5 → 0.12.6

**Theme**: Make `bob-hermes-adapter` discoverable + buildable through
the canonical install path. `HERMES_IMAGE` is now documented in
`.env.example`, and `deploy-prod.sh` builds the adapter image
automatically (gated on `hermes-adapter/Dockerfile` existing).

- **Schema migrations**: none.
- **Env vars**: new — `HERMES_IMAGE`, `HERMES_DEFAULT_TIMEOUT_SEC`,
  `HERMES_USE_GATEWAY`, `HERMES_GATEWAY_URL`. All have sensible
  defaults; the Hermes backend stays dormant if `HERMES_IMAGE` is
  empty.
- **Downtime**: ~10 s for the restart (no migrations).
- **Action**: `git pull && bash deploy-prod.sh`.

The redeploy auto-builds `bob-hermes-adapter:latest`. If you already
had `HERMES_IMAGE` set in `.env` (manually, before 0.12.6), your value
takes precedence — `deploy-prod.sh` reads it.

First-time Hermes operators: open the updated `.env.example`, copy
the new `HERMES_IMAGE=…` block into your `.env`, then redeploy. New
flag `--no-hermes` skips the build for stripped-down deployments.

#### Heads-up: small models via Hermes ≠ Claude Opus via claude-agent

If you've been comparing `qwen2.5:14b` (Hermes backend) responses
against `claude-agent:opus`, expect different behavior:

- `claude-agent:*` runs Claude Code directly with its own tool stack
  (web_search, web_fetch). It can autonomously research and synthesize.
- `qwen2.5:14b` via Hermes runs inside an adapter that exposes
  `tools: []` by design — no API-keyed search tools are wired up.
  Small models correctly return `NEEDS_INPUT: …` asking for clarification.

This is not a regression. Wiring search tools into the Hermes adapter
is a separate roadmap item.

### 0.12.4 → 0.12.5

**Theme**: Self-heal `lab_resources` + `qdrant_staging` volume
ownership on every redeploy. CSO #3 dropped root for both
`bob-api` and `bob-sandbox` (USER 1000); Docker volumes ever
written by a pre-CSO #3 (root) container kept root ownership and
caused `Errno 13: Permission denied` on every lab Run / agent
Run after upgrading to 0.12.x.

- **Schema migrations**: none.
- **Env vars**: no changes.
- **Downtime**: ~10 s for the restart.
- **Action**: `git pull && bash deploy-prod.sh`.

`deploy-prod.sh` now runs a throwaway `alpine:3.20` container
between the build step and the DB migration step that `chown -R
1000:1000`s both named volumes. Idempotent — no-op when ownership
already matches — so safe on every redeploy and on fresh installs.

Watch for the new `▶ Ensuring volume ownership (CSO #3 — UID 1000)…`
/ `✔ Volume ownership ensured (uid 1000)` lines during deploy.

#### If you can't redeploy right now

Operators who hit the trap (lab or agent Run fails with `Errno 13:
Permission denied: '/data/lab_resources/<lab_id>/…'`) and don't
want to wait for the full redeploy can run the chown directly:

```bash
docker run --rm -v bob-manager_lab_resources:/data alpine:3.20 \
    chown -R 1000:1000 /data
docker run --rm -v bob-manager_qdrant_staging:/data alpine:3.20 \
    chown -R 1000:1000 /data
```

No container restart needed afterwards — Linux re-reads ownership
per syscall, so the next lab/agent Run picks it up.

### 0.12.3 → 0.12.4

**Theme**: Fixes a 0.12.3 regression — the migration nulled
`orchestrator_settings.orchestrator_model` but the API response
schema still declared the field non-nullable, so `GET /settings`
500'd and the Default Model section disappeared from the FE.

- **Schema migrations**: none.
- **Env vars**: no changes.
- **Downtime**: ~10 s for the restart.
- **Action**: `bash deploy-prod.sh` (canonical install/upgrade path).

The fix is two annotations:
`OrchestratorSettingsResponse.orchestrator_model: str | None = None`
and `OrchestratorSettings.orchestrator_model: Mapped[str | None]`
(dropping the Python-side `default="qwen2.5:72b"` that would have
re-introduced the phantom default whenever the singleton row was
lazily created).

#### About lab Run 500s ("bob-manager-bob-sandbox image not found")

If you've been seeing `Failed to run instance` or `500` on **Run**,
the cause is that the sandbox image hasn't been built locally.
`bob-sandbox` has `profiles: [build-only]`, so plain
`docker compose up -d --build` skips it. **Use `bash deploy-prod.sh`
— it builds the sandbox image explicitly.** Or do it once by hand:

```bash
docker compose build bob-sandbox
docker compose up -d
```

After the sandbox image is locally tagged as
`bob-manager-bob-sandbox:latest` (note: the `name: bob-manager` pin
added in 0.12.3 makes this consistent across clone directories),
**Run** completes with HTTP 202.

### 0.12.2 → 0.12.3

**Theme**: Closes two more first-install traps — a phantom default
model and a hardcoded sandbox image name that broke any clone not
in a directory called `bob-manager`.

- **Schema migration**: 1 new revision `0015_orchestrator_model_default`.
  Drops the bogus column default and nulls out singleton rows still
  carrying `'qwen2.5:72b'`. Additive + idempotent. Runs automatically.
- **Env vars**: no changes.
- **Downtime**: ~10 s for the migration + restart.
- **Action required**: just `git pull && docker compose up -d --build`.

#### What was broken

`control-plane/app/migrations/init.sql` declared
`orchestrator_settings.orchestrator_model VARCHAR(255) DEFAULT 'qwen2.5:72b'`.
The singleton INSERT didn't override, so every fresh install began
with the default set to a 72B model nobody had loaded. The FE
`<select>` rendered the first valid option visually but didn't
actually persist anything until the user explicitly clicked the
dropdown again. Lab dispatcher read the literal `'qwen2.5:72b'`
from the DB → no matching model → 422 with "no default model set".

#### What 0.12.3 changes

- Migration `0015` clears the phantom default; new installs and
  affected upgrades land with `orchestrator_model=NULL`.
- Dispatcher (`/labs/{id}/run`, `/library-agents/.../inject`) falls
  back to the first registered model with a `WARNING` log when the
  configured default is missing or stale. Only 422's if no models
  are registered at all.
- FE dropdown shows `— pick a model —` when the saved default is
  empty or off-list, with a hint surfacing the actual saved value.

If you already manually picked a working default (e.g. `hermes3:8b`),
your setting is preserved — the migration only nulls rows still on
`'qwen2.5:72b'`.

### 0.12.1 → 0.12.2

**Theme**: Critical fix — 0.12.1 left fresh installs still broken
because the actual root cause was Alembic schema drift, not the
provider-approval gate. 0.12.2 fixes the startup logic so fresh
DBs reach head correctly.

- **Schema migrations**: none new (0014 stays head).
- **Env vars**: no changes.
- **Downtime**: ~10 s for the restart on a healthy DB.
- **Action required for anyone who installed 0.11.0–0.12.1**: see
  recovery section below.

#### What was broken

`control-plane/app/main.py` stamped Alembic to `head` whenever
`blog_posts.slug` existed in the schema. That column was in
`init.sql`, but the rest of `init.sql` had drifted nine revisions
behind the migration chain. Fresh installs therefore ended up with
`alembic_version='0014_secret_at_rest'` (lying) and a schema
missing every column added by migrations 0005-0014:
`ai_providers.pending_approval`, `lab_agents.backend`,
`library_agents.backend`, `mcp_servers` (entire table),
`blog_tokens.token_hash`, `access_tokens.token_hash`.

Visible symptom: orchestrator console crashes on
`column ai_providers.pending_approval does not exist`, models tab
empty, no labs creatable.

#### Recovery for already-installed 0.11.0 / 0.12.0 / 0.12.1 deployments

**0.12.2 self-heals the broken-stamp state on startup.** Just pull
and restart:

```bash
cd /path/to/boblabs
git pull
docker compose up -d --build
docker compose logs -f bob-api | grep -i alembic
```

If your DB was in the broken state, you'll see:

```
[WARNING] Alembic: detected broken-stamp from 0.11.0-0.12.1
          (alembic_version at head but schema missing migration 0005+);
          re-stamping to 0001_baseline so catch-up migrations replay
[INFO]    Running upgrade 0001_baseline -> 0002_blog_slug, …
[INFO]    Running upgrade 0013_agent_backend -> 0014_secret_at_rest, …
[INFO]    Alembic: migrations applied
```

Every migration past 0001 is idempotent (`IF NOT EXISTS` / `DO $$`
guards), so the replay on a partially-broken DB is safe — no
data loss, no duplicate-key errors. Verify when done:

```bash
docker exec bob-db psql -U bob -d bob_manager -c \
  "SELECT version_num FROM alembic_version;"
# Expected: 0014_secret_at_rest
```

If you prefer to wipe and start fresh (no real data yet):

```bash
docker compose down -v          # -v removes the bob-db volume
git pull
docker compose up -d --build
```

### 0.12.0 → 0.12.1

**Theme**: Fixes the "no models in console" first-install trap by
flipping the default for auto-discovered providers from
pending-on-sight to auto-approved.

- **Schema migrations**: none.
- **Env vars (new, optional)**: `BOB_REQUIRE_PROVIDER_APPROVAL`
  (default `false`).
- **Downtime**: ~10 s for the restart.

#### ⚠️ Default-behavior change (security-relevant)

Before 0.12.1, every auto-discovered AI provider (Ollama, Claude CLI,
ComfyUI, …) landed `pending_approval=True, is_active=False`. The
dispatcher refused to route until an admin approved it. The gate had
**no UI surface and no docs**, so first-time installers saw an empty
model list with no hint.

In 0.12.1 the **default flips to auto-approve**. New providers are
immediately dispatchable.

**If you relied on the strict gate** (the cluster I behavior from
0.10.0+), add to your control-plane `.env` before restarting:

```
BOB_REQUIRE_PROVIDER_APPROVAL=true
```

Then restart `bob-api`. Newly-discovered providers will once again
land as pending. The orchestrator console now renders pending rows
grayed-out with an inline **Approve** button (one click), and the
server logs a clear `WARNING` with the curl command for headless
approval.

**Threat model reminder**: the strict gate mitigates a leaked
`AGENT_SECRET` being used to register a malicious `base_url`. If
your agent network is fully trusted, the default is appropriate.

### 0.11.1 → 0.12.0

**Theme**: Two new top-level capabilities — real Hermes agents (Nous
Research) and a Claude CLI provider. Two additive schema migrations.

- **Schema migrations**: 2 new revisions.
  | Revision | Purpose |
  |---|---|
  | `0012_mcp_servers` | New table for MCP server definitions |
  | `0013_agent_backend` | Adds `backend` column to `ai_agents` (default `native`) |

  Both are additive; no data conversion required. Run
  `alembic upgrade head` (handled automatically by `deploy-prod.sh`).
- **Env vars**:
  - **New (Hermes — only set if you want to use it)**: `HERMES_IMAGE`,
    `HERMES_DEFAULT_TIMEOUT_SEC`, `HERMES_MEM_MB`, `HERMES_CPUS`.
    Without `HERMES_IMAGE` set, the backend feature is hidden in the
    UI; existing labs continue running unchanged.
  - **New (Claude CLI — only on GPU servers that opt in)**:
    `CLAUDE_CODE_OAUTH_TOKEN` (Max subscription token from
    `claude setup-token`), `CLAUDE_CLI_MODELS`, `CLAUDE_CLI_PORT`,
    `CLAUDE_CLI_CONCURRENCY`, `CLAUDE_CLI_TIMEOUT_SEC`,
    `CLAUDE_CLI_TOOLS`, `CLAUDE_CLI_API_KEY`. See
    [docs/CLAUDE_CLI.md](docs/CLAUDE_CLI.md) for setup. The sidecar
    runs in `claude-cli/docker-compose.yml` on each GPU server that
    should expose its Max subscription — it is **not** brought up by
    the bob-manager root compose stack.
- **Downtime**: ~30 s for migration + restart.
- **No breaking changes.** Existing agents keep `backend='native'`
  by default. Labs that don't switch to Hermes or claude-cli
  providers continue identically.
- **Hermes setup** (only if you want to use it):
  1. Build the adapter image once: `docker build -t bob-hermes-adapter:latest hermes-adapter/`
  2. Set `HERMES_IMAGE=bob-hermes-adapter:latest` in `.env`.
  3. From the agent edit dialog, pick `backend: hermes`.
- **Claude CLI setup** (only on GPU servers that should expose a Max sub):
  1. On the GPU server: `cd claude-cli && cp .env.example .env`
  2. Run `claude setup-token` locally, paste the `sk-ant-oat01-*` token into `.env` as `CLAUDE_CODE_OAUTH_TOKEN`.
  3. `docker compose up -d` (in `claude-cli/`).
  4. The agent's metrics tick auto-discovers it; an admin approves the resulting `claude_cli-<host>` provider once.

### 0.11.0 → 0.11.1

**Theme**: Security patch — gate the metrics router + drop container processes off root.

- **Schema migrations**: none.
- **Env vars**: none added or removed.
- **Downtime**: ~10s for the rebuild + restart (`./deploy-prod.sh`).
- **⚠️ Possibly breaking for scrapers**: if any external client was
  hitting `/api/v1/metrics/*` without an access token, it will now
  receive `401`. Add an access token with the `infra` scope (or
  admin auth) to the request. Internal callers from bob-ui already
  carry the JWT — no change needed there.
- **No data migration required.** Existing containers will be
  rebuilt and restarted as a non-root user; any files written into
  shared volumes (`/data/lab_resources`, `/data/rag_staging`,
  `/data/lightrag`) must be readable + writable by the new uid. If
  you mounted host paths with restrictive ownership, run
  `chown -R 1000:1000 <path>` on the volume before restart.

### 0.10.0 → 0.11.0

**Theme**: Process maturity for v1.0 prep. CI, lint, OpenAPI commitment,
versioning policy. No runtime behavior changes.

- **Schema migrations**: none.
- **Env vars**: none added or removed.
- **Downtime**: ~10s for the restart.
- **What changed**:
  - Codebase formatted with Ruff (`ruff check --fix` + `ruff format`).
    No behavior change; CI now enforces `ruff check .` and `ruff format --check .` on every PR.
  - [`docs/openapi.json`](docs/openapi.json) is now committed and drift-checked in CI. Use it directly instead of booting the stack to read the spec.
  - New: [`VERSIONING.md`](VERSIONING.md) defines the v1.0 public-API contract.
  - New: this file, `UPGRADE.md`.
  - New: `.github/workflows/ci.yml` runs Python tests, Ruff, OpenAPI drift, frontend tests, and a compose-config smoke on every PR.
  - New: `.github/ISSUE_TEMPLATE/*` and `.github/PULL_REQUEST_TEMPLATE.md`.
- **What stayed the same**: every REST endpoint, every database column, every env var, every consumer-app HMAC header.

### 0.9.0 → 0.10.0

**Theme**: Phase 5 audit closeout. Security gates across the auth +
ACL surface, repo-layer hardening, sandbox lifecycle, trading
precision overhaul.

- **Schema migrations**: 8 new revisions (`0004` → `0011`). All
  additive except `0011_trading_precision`, which converts decimal
  amount strings to wei-integer + per-asset decimals — see the
  warning below.
- **Env vars**: none added.
- **Downtime**: ~30 seconds for the migration step. The
  `0011_trading_precision` data conversion is **one-way**.
- **⚠️ Back up your bob-db before upgrading**: if you have live
  trading positions in `portfolio_snapshots`, `wallet_holdings`, or
  `trading_positions`, the `0011` migration converts decimal strings
  to integer wei amounts. Recovery requires the pg_dump.
- **What's in the bag**:

  | Revision | Purpose |
  |---|---|
  | `0004_workflows_acl` | `owner_id` / `editor_ids` / `viewer_ids` on workflows |
  | `0005_ai_providers_pending` | `pending_approval` flag on auto-discovered providers |
  | `0006_token_hashes` | Access tokens stored as Argon2id hashes (was plaintext) |
  | `0007_portfolio_snapshots_pk` | Composite PK fix |
  | `0008_lab_web3_default` | Default on `lab_web3_access.id` |
  | `0009_workflow_step_acl_shape` | UNIQUE + CHECK on workflow steps |
  | `0010_lab_loop_type_check` | CHECK matching `Literal` alias |
  | `0011_trading_precision` | **wei-integer amounts + decimals** (data migration) |

- **New gates that may affect ops**:
  - Auto-discovered AI providers land as `pending_approval=True, is_active=False`. Admin must approve via the panel before traffic flows.
  - Workflow `execute` requires `EDIT` permission (was `VIEW`).
  - `/ws/client` now rejects unauthenticated connections.
  - `direct_cmd_exec` was removed; shell paths route through the sandbox HTTP API with command allow-list.

### 0.x → 0.9.0

Initial open-source release. No upgrade path before this — fresh deployments only. See [`docs/INSTALL_PROD.md`](docs/INSTALL_PROD.md) for first-time setup.

---

## When upgrading hits a snag

1. **Migration failed mid-run** — the schema may be in a partial state.
   Restore from your `pg_dump`, then file an issue with the alembic
   output (the revision that crashed + the SQL error).
2. **Health check returns 500** — check `docker logs bob-api`. The
   most common cause post-upgrade is an env var that was added in
   the new version and not yet set. Compare your `.env` against
   `.env.example` after each upgrade.
3. **Frontend shows old version** — hard-refresh (`Ctrl+Shift+R`) to
   bypass the browser cache. The version is shown in the bottom of
   `/admin`.
4. **Anything else** — open an issue with: pre-upgrade version,
   post-upgrade version, `docker logs bob-api` and `docker logs bob-ui`
   output, and `curl /api/v1/health` response.
