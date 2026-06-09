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
