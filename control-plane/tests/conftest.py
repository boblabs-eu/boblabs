"""Pytest fixtures for the control-plane test suite (Phase 5 Session 1.5).

Design notes:
- The test DB is brought up by `make test-up` (Postgres 16 on :5433) and
  `alembic upgrade head` runs against it before pytest. The conftest does
  NOT manage container or schema lifecycle — it expects the DB to be
  ready and migrated.
- Env vars (DATABASE_URL, JWT_SECRET, ADMIN_SECRET, BOB_API_ALLOW_MULTI_WORKER)
  are exported by the `make test-only` target before pytest spawns. We
  do not patch them here because `app.config.settings` is read at import
  time — setting env inside conftest would be too late.
- Test isolation: TRUNCATE all `Base.metadata` tables after each test
  (RESTART IDENTITY, CASCADE). Single-worker for v1; if/when the suite
  grows past ~5 minutes wall time, switch to schema-per-worker via
  pytest-xdist + a unique-name schema setup hook.
- No ACL/auth mocking — that surface IS what's under test. JWTs are
  real (signed with the test JWT secret), Lab rows are real, ACL JSONB
  is real Postgres JSONB.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from typing import AsyncIterator, Callable

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

# Fail fast if the test env wasn't set up (Makefile target sets these).
_REQUIRED_ENV = ("DATABASE_URL", "JWT_SECRET", "BOB_API_ALLOW_MULTI_WORKER")
_missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
if _missing:
    raise RuntimeError(
        f"Test env not configured. Missing: {_missing}. "
        "Run via `make test-only` (or `make test`) from repo root."
    )
if "bob_test" not in os.environ["DATABASE_URL"]:
    raise RuntimeError(
        f"DATABASE_URL={os.environ['DATABASE_URL']!r} does not name the "
        "test DB (bob_test). Refusing to run tests against a non-test "
        "database — this guard prevents accidental TRUNCATE of dev/prod."
    )


# ── Imports (after env validation) ─────────────────────────────────────

# Override the production engine with NullPool for tests BEFORE app.main
# imports anything that captures the sessionmaker binding. The prod engine
# uses pool_size=20 + max_overflow=10 which leaves asyncpg connections in a
# half-released transactional state between tests, producing
# "cannot use Connection.transaction() in a manually started transaction"
# during the truncate fixture. NullPool gives a fresh connection per
# checkout, which sidesteps the issue entirely.

import app.database as _db_mod  # noqa: E402
from sqlalchemy import pool  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

_test_engine = create_async_engine(
    os.environ["DATABASE_URL"],
    echo=False,
    poolclass=pool.NullPool,
)
_test_async_session = async_sessionmaker(
    _test_engine, expire_on_commit=False,
)
_db_mod.engine = _test_engine
_db_mod.async_session = _test_async_session

from app.api.dependencies import create_access_token  # noqa: E402
from app.database import async_session, engine  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.orchestrator import Lab  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402


# ── Truncate-between-tests isolation ───────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _truncate_all_tables() -> AsyncIterator[None]:
    """TRUNCATE every Base-known table BEFORE each test.

    Setup-time truncate (not teardown) so that a failed test leaves its
    rows visible for debugging via `psql` against the test DB. The next
    test wipes them on its own setup.

    alembic_version is not in Base.metadata, so it is preserved — we
    do not want to re-stamp/re-migrate between tests.
    """
    table_names = [t.name for t in reversed(Base.metadata.sorted_tables)]
    if table_names:
        async with async_session() as session:
            await session.execute(text(
                f"TRUNCATE TABLE {', '.join(table_names)} "
                f"RESTART IDENTITY CASCADE"
            ))
            await session.commit()
    yield


# ── DB session fixture ────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db() -> AsyncIterator:
    """Yield an AsyncSession for test setup + assertions.

    This is the *test* session — separate from whatever session the app's
    `get_db` dependency hands route handlers during an HTTP call. Both
    talk to the same Postgres but through independent connections, which
    matches production behavior (each request gets its own session).
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── JWT + user fixtures ───────────────────────────────────────────────
#
# There is no `User` table in bob-api — JWTs are stateless dicts with
# `sub` (email) and `role` (admin | user). Fixtures return the claim
# dict so tests that call `check_permission` directly can use it as-is,
# AND a `token` attribute (the encoded JWT) so HTTP-client fixtures
# can build Authorization headers.


def _make_user(email: str, role: str = "user") -> dict:
    claims = {"sub": email, "role": role}
    token = create_access_token(claims, expires_delta=timedelta(hours=1))
    # Embed token + return same dict shape jose decodes back to
    return {**claims, "token": token, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
def admin_user() -> dict:
    return _make_user("admin@test.local", role="admin")


@pytest.fixture
def regular_user() -> dict:
    return _make_user("user@test.local", role="user")


@pytest.fixture
def editor_user() -> dict:
    return _make_user("editor@test.local", role="user")


@pytest.fixture
def viewer_user() -> dict:
    return _make_user("viewer@test.local", role="user")


@pytest.fixture
def other_user() -> dict:
    """A user that owns no resource by default — used to test cross-tenant denial."""
    return _make_user("other@test.local", role="user")


@pytest.fixture
def make_user() -> Callable[..., dict]:
    """Factory for ad-hoc users in tests that need more than the standard four."""
    return _make_user


def _make_expired_token(email: str = "expired@test.local", role: str = "user") -> str:
    # Negative timedelta makes the `exp` claim immediately in the past.
    return create_access_token(
        {"sub": email, "role": role},
        expires_delta=timedelta(seconds=-1),
    )


@pytest.fixture
def expired_token() -> str:
    return _make_expired_token()


# ── HTTP client fixtures ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def anonymous_client() -> AsyncIterator[AsyncClient]:
    """AsyncClient with no Authorization header."""
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app),
        base_url="http://test",
    ) as client:
        yield client


@pytest_asyncio.fixture
async def admin_client(admin_user) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app),
        base_url="http://test",
        headers=admin_user["headers"],
    ) as client:
        yield client


@pytest_asyncio.fixture
async def user_client(regular_user) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app),
        base_url="http://test",
        headers=regular_user["headers"],
    ) as client:
        yield client


@pytest_asyncio.fixture
async def make_client():
    """Build an AsyncClient with a custom user's auth headers."""
    clients: list[AsyncClient] = []

    async def _build(user: dict | None = None) -> AsyncClient:
        headers = user["headers"] if user else {}
        c = AsyncClient(
            transport=ASGITransport(app=fastapi_app),
            base_url="http://test",
            headers=headers,
        )
        clients.append(c)
        return c

    yield _build
    for c in clients:
        await c.aclose()


# ── Lab factory ───────────────────────────────────────────────────────


def _default_acl(owner_email: str) -> dict:
    return {"owner": owner_email, "editors": [], "viewers": []}


@pytest_asyncio.fixture
async def lab_factory(db):
    """Insert a real Lab row with an ACL.

    Usage::

        lab = await lab_factory(owner=admin_user)
        lab = await lab_factory(owner=admin_user, acl={"owner": "x", ...})
        lab = await lab_factory(owner=admin_user, editors=[editor_user])

    Returns the Lab ORM instance after commit (so `lab.id` is populated).
    """

    async def _make(
        *,
        owner: dict | None = None,
        editors: list[dict] | None = None,
        viewers: list[dict] | None = None,
        acl: dict | None = None,
        name: str | None = None,
        is_public: bool = False,
        **lab_kwargs,
    ) -> Lab:
        owner_email = (owner or {}).get("sub", "admin@test.local")
        if acl is None:
            acl = {
                "owner": owner_email,
                "editors": [e["sub"] for e in (editors or [])],
                "viewers": [v["sub"] for v in (viewers or [])],
            }
        lab = Lab(
            id=uuid.uuid4(),
            name=name or f"test-lab-{uuid.uuid4().hex[:8]}",
            acl=acl,
            is_public=is_public,
            **lab_kwargs,
        )
        db.add(lab)
        await db.commit()
        await db.refresh(lab)
        return lab

    return _make


# ── Asyncio event-loop policy ─────────────────────────────────────────
# Configured via pytest.ini:
#   asyncio_mode = auto
#   asyncio_default_fixture_loop_scope = session
# pytest-asyncio 0.24 deprecates user-defined event_loop fixtures;
# we rely on its defaults.
