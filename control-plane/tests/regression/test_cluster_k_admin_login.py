"""Cluster K — admin_login uses hmac.compare_digest, not `==`.

The audit flagged plaintext `==` comparison of `settings.admin_secret`
against the user-supplied password — early-exit timing leak. Fix: use
`hmac.compare_digest`.

These tests assert:
1. Wrong password → 401.
2. Correct password → 200 + JWT.
3. Compare-digest is used (timing-safe — we cannot test wall-clock
   timing reliably, but we can patch hmac.compare_digest and assert it
   was called).
4. Wrong-length passwords still get 401 (`==` would short-circuit on
   length mismatch; compare_digest does not — both must return 401).
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.api.dependencies import get_current_user
from fastapi.security import HTTPAuthorizationCredentials

pytestmark = pytest.mark.regression


@pytest.mark.asyncio
async def test_admin_login_wrong_password_401(anonymous_client):
    r = await anonymous_client.post("/api/v1/public/admin-login", json={
        "password": "definitely-not-the-admin-secret",
    })
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_admin_login_correct_password_returns_jwt(anonymous_client):
    secret = os.environ["ADMIN_SECRET"]
    r = await anonymous_client.post("/api/v1/public/admin-login", json={
        "password": secret,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    # Round-trip the token via get_current_user
    payload = await get_current_user(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=body["access_token"])
    )
    assert payload["role"] == "admin"


@pytest.mark.asyncio
async def test_admin_login_uses_compare_digest(anonymous_client):
    """Patch hmac.compare_digest and assert the route called it."""
    import hmac
    original = hmac.compare_digest
    called = {"count": 0}

    def spy(a, b):
        called["count"] += 1
        return original(a, b)

    with patch("hmac.compare_digest", side_effect=spy):
        await anonymous_client.post(
            "/api/v1/public/admin-login",
            json={"password": "wrong"},
        )
    assert called["count"] >= 1, (
        "admin_login did not call hmac.compare_digest — cluster K regression"
    )


@pytest.mark.asyncio
async def test_admin_login_length_mismatch_still_401(anonymous_client):
    """Length-mismatched password must still 401, not 500."""
    r = await anonymous_client.post("/api/v1/public/admin-login", json={
        "password": "x",  # short
    })
    assert r.status_code == 401, r.text
