"""Unit tests for app.api.dependencies — get_current_user + require_admin.

Covers:
- Valid JWT → claims dict returned
- Expired JWT → 401
- Malformed JWT → 401
- Wrong-secret JWT → 401
- Missing Authorization header → 401 (via HTTPBearer)
- require_admin: admin role → user dict; non-admin → 403; anonymous → 401
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from app.api.dependencies import (
    create_access_token,
    get_current_user,
    require_admin,
)
from app.config import settings
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ── get_current_user ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_current_user_valid_admin(admin_user):
    payload = await get_current_user(_creds(admin_user["token"]))
    assert payload["sub"] == "admin@test.local"
    assert payload["role"] == "admin"
    assert "exp" in payload


@pytest.mark.asyncio
async def test_get_current_user_valid_regular(regular_user):
    payload = await get_current_user(_creds(regular_user["token"]))
    assert payload["sub"] == "user@test.local"
    assert payload["role"] == "user"


@pytest.mark.asyncio
async def test_get_current_user_expired(expired_token):
    with pytest.raises(HTTPException) as exc:
        await get_current_user(_creds(expired_token))
    assert exc.value.status_code == 401
    assert "Invalid or expired" in exc.value.detail


@pytest.mark.asyncio
async def test_get_current_user_malformed():
    with pytest.raises(HTTPException) as exc:
        await get_current_user(_creds("not.a.jwt"))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_wrong_secret():
    # Token signed with a *different* secret — must be rejected.
    bad_token = jwt.encode(
        {"sub": "attacker@evil.local", "role": "admin"},
        "completely-different-secret",
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(HTTPException) as exc:
        await get_current_user(_creds(bad_token))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_wrong_algorithm():
    # Token signed with HS512 when settings.jwt_algorithm is HS256.
    other_alg = "HS512" if settings.jwt_algorithm != "HS512" else "HS384"
    bad_token = jwt.encode(
        {"sub": "x@y", "role": "admin"},
        settings.jwt_secret,
        algorithm=other_alg,
    )
    with pytest.raises(HTTPException) as exc:
        await get_current_user(_creds(bad_token))
    assert exc.value.status_code == 401


# ── require_admin ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_require_admin_pass(admin_user):
    user = await require_admin(user={"sub": admin_user["sub"], "role": "admin"})
    assert user["role"] == "admin"


@pytest.mark.asyncio
async def test_require_admin_rejects_user():
    with pytest.raises(HTTPException) as exc:
        await require_admin(user={"sub": "u@x", "role": "user"})
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_rejects_no_role():
    with pytest.raises(HTTPException) as exc:
        await require_admin(user={"sub": "u@x"})
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_rejects_empty_role():
    with pytest.raises(HTTPException) as exc:
        await require_admin(user={"sub": "u@x", "role": ""})
    assert exc.value.status_code == 403


# ── HTTP-level integration sanity ─────────────────────────────────
#
# Hit a known admin-only route to confirm the dep wires up correctly
# end-to-end. We use /api/v1/admin/labs because admin_labs.py uses
# `Depends(require_admin)` (cluster G + sweep verified this).


@pytest.mark.asyncio
async def test_admin_route_anonymous_returns_401_or_403(anonymous_client):
    r = await anonymous_client.get("/api/v1/admin/labs")
    # HTTPBearer raises 403 by default when no header present (FastAPI quirk);
    # 401 when a bad header is given. Either is acceptable from an auth
    # standpoint — what matters is that the route does not return 200.
    assert r.status_code in (401, 403), r.text


@pytest.mark.asyncio
async def test_admin_route_user_returns_403(user_client):
    r = await user_client.get("/api/v1/admin/labs")
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_admin_route_admin_returns_200(admin_client):
    r = await admin_client.get("/api/v1/admin/labs")
    assert r.status_code == 200, r.text


# ── create_access_token round-trip ────────────────────────────────


@pytest.mark.asyncio
async def test_create_access_token_round_trip():
    tok = create_access_token(
        {"sub": "round@trip", "role": "user"}, expires_delta=timedelta(minutes=5)
    )
    payload = await get_current_user(_creds(tok))
    assert payload["sub"] == "round@trip"
    assert payload["role"] == "user"
