"""Wave 4 O.1 — admin_consumer_apps requires admin role.

Pre-fix: every route under /api/v1/admin/consumer-apps used
`Depends(get_current_user)` — any authenticated user could mint or
revoke HMAC integration credentials.

Post-fix: all 4 routes use `Depends(require_admin)`.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/admin/consumer-apps"),
    ("POST", "/api/v1/admin/consumer-apps"),
    ("DELETE", "/api/v1/admin/consumer-apps/00000000-0000-0000-0000-000000000000"),
    ("DELETE", "/api/v1/admin/consumer-apps/00000000-0000-0000-0000-000000000000/permanent"),
])
@pytest.mark.asyncio
async def test_non_admin_blocked(user_client, method, path):
    r = await user_client.request(
        method, path,
        json={"app_id": "spam"} if method == "POST" else None,
    )
    assert r.status_code == 403, (
        f"{method} {path} returned {r.status_code} for non-admin user; "
        "expected 403 — Wave 4 O.1 regression"
    )


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/admin/consumer-apps"),
    ("DELETE", "/api/v1/admin/consumer-apps/00000000-0000-0000-0000-000000000000"),
])
@pytest.mark.asyncio
async def test_anonymous_blocked(anonymous_client, method, path):
    r = await anonymous_client.request(method, path)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_admin_can_list(admin_client):
    r = await admin_client.get("/api/v1/admin/consumer-apps")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_admin_can_create_and_secret_is_one_time(admin_client):
    r = await admin_client.post(
        "/api/v1/admin/consumer-apps",
        json={"app_id": "test-app-1", "name": "Test", "notes": ""},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["app_id"] == "test-app-1"
    assert body["secret"], "secret not returned at creation time"

    # The list endpoint must NOT echo the secret back.
    r2 = await admin_client.get("/api/v1/admin/consumer-apps")
    assert r2.status_code == 200
    for app in r2.json():
        assert "secret" not in app, (
            "list endpoint leaks consumer-app secret — would defeat one-time secret design"
        )
