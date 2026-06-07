# Testing

Two test gates ship in this repo.

| Gate | Command | What it covers | Wall time |
|---|---|---|---|
| **Unit + regression** | `make test` | pytest suite under [control-plane/tests/](../control-plane/tests/) — auth/ACL/permissions, every shipped security cluster (A–R + Wave 4), repo behavior, route auth boundaries, SSRF guard, RAG sanitizer | ~30s |
| **Integration smoke** | `make integration` | The pre-existing [scripts/](../scripts/) suite — runs against the live dev stack, exercises every tool, the consumer-app HMAC channel, sandbox containers, GPU services | minutes |

Both gates are needed for a green release.

## `make test` — the pytest suite

Brings up an **ephemeral Postgres 16 on :5433** via `docker-compose.test.yml`,
runs `alembic stamp 0001_baseline` + `alembic upgrade head` to get the
prod schema, then executes pytest inside the `bob-manager-bob-api`
image so the Python + system deps match production exactly.

```sh
make test         # full cycle: up DB, migrate, pytest, tear down
make test-up      # bring up DB and leave it running
make test-only    # pytest against an already-up DB (iteration loop)
make test-down    # tear down the DB
make test-shell   # drop into a shell in the test container

# Pass extra pytest args:
PYTEST_ARGS="-k auth -v" make test-only
```

### What runs in pytest

```
control-plane/tests/
  unit/         Pure Python — auth dep, ACL check_permission, JSONB shape
  regression/   One file per shipped security cluster (A–R + Wave 4)
                + 3 skips for showroom-api/UI clusters (C, Q) that
                belong in those services' own future test suites
  routes/       Route auth boundary sweep — introspects every router
                in app/api/routes/ and asserts each route has
                auth dep (or is in the KNOWN_OPEN_ROUTES snapshot)
  repositories/ Repo behavior + SQL query counter for N+1 detection;
                xfails track Session 2 (P01–P05) pagination caps
  services/     ssrf_guard redirect rejection, RAG sanitizer,
                authorization service edge cases
```

### Fixtures (defined in [conftest.py](../control-plane/tests/conftest.py))

- `db` — fresh AsyncSession against the test Postgres
- `admin_user` / `regular_user` / `editor_user` / `viewer_user` /
  `other_user` — dicts with `{sub, role, token, headers}` for real
  JWTs signed by `settings.jwt_secret`
- `anonymous_client` / `admin_client` / `user_client` /
  `make_client(user)` — httpx.AsyncClient with auth headers preset
- `lab_factory(owner=..., editors=..., viewers=..., acl=...)` —
  inserts a real Lab row with real JSONB ACL
- Autouse TRUNCATE-between-tests on every `Base.metadata` table

### Adding a new test

Drop the file under the right subdir (or create a new one), use the
fixtures, prefix HTTP routes with `/api/v1/`. Examples:

```python
# Pure unit
def test_my_pure_logic():
    assert ...

# Async + DB
@pytest.mark.asyncio
async def test_repo_thing(db, admin_user, lab_factory):
    lab = await lab_factory(owner=admin_user)
    ...

# HTTP integration
@pytest.mark.asyncio
async def test_route_thing(user_client):
    r = await user_client.get("/api/v1/...")
    assert r.status_code == 403
```

### Markers

- `regression` — A–R + Wave 4 regression suite
- `route_auth` — route auth boundary sweep
- `repo` — repository-layer tests
- `service` — service-layer tests

`pytest -m regression` runs just the security-cluster regression set.

## `make integration` — scripts/ smoke suite

Runs against the dev stack (`docker compose up -d` brings it up on
`:3000` / `:4000`; bob-api lives at `:8888`). Three steps:

```sh
make integration
  ↳ docker compose exec -T bob-api python /app/scripts/test-all-tools.py
  ↳ python3 scripts/smoke_consumer_app_agent.py
  ↳ python3 scripts/smoke_consumer_app_rag.py
```

`test-all-tools.py` exercises 40+ agent tools against a real lab with
safe minimal args. Tier A+B blocking-stack-trace failures fail the
gate; Tier E/F "not configured" failures are tolerated. Reports land
at `/tmp/tool-test-report.md` inside bob-api.

`smoke_consumer_app_*.py` sign HMAC requests and round-trip the
internal-apps surface. They need `BOB_APP_ID` + `BOB_APP_SECRET`
exported in the shell (see the script docstrings).

## When tests fail

| Symptom | Likely cause | Fix |
|---|---|---|
| `cannot use Connection.transaction() in a manually started transaction` | Test pool inherited an unclean session | Re-run; if persistent, the test changed `conftest._truncate_all_tables` |
| `5433` not in DATABASE_URL | The Makefile target wasn't used | `make test-only` (don't run pytest directly without the env) |
| `Database not migrated` | Test DB came up before init.sql finished | `make test-down && make test-up` |
| New route flagged "WITHOUT auth deps" | Someone added a route without an auth Depends() | Add `Depends(get_current_user)`/`require_admin` to the handler, OR add the path to `KNOWN_OPEN_ROUTES` in `tests/routes/test_route_auth_sweep.py` |
| xfail flipped to xpass | The Session 2/3 fix landed — remove the `xfail` marker | Per cluster, see the xfail `reason` |

## Why no transaction rollback

We use TRUNCATE between tests instead of the standard transaction-rollback
pattern. Three reasons:
1. Truncate is cheap (~1ms for our schema).
2. asyncpg+SQLAlchemy interact badly with nested transactions when
   the test holds a session AND a route handler opens its own.
3. Setup-time truncate (not teardown) means a failed test leaves its
   rows in the DB for inspection via `psql` against `:5433`.

If the suite grows past ~5 minutes, switch to schema-per-worker via
pytest-xdist — left out of v1.
