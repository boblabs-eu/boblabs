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
