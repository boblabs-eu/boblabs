"""Extra authorization-service tests beyond what unit/ already covers.

Targets edge cases that show up in route handlers but aren't in the
core unit suite:
  - check_permission with mixed-case email comparisons (lowercase
    canonical assumption).
  - filter_query_by_access doesn't apply where clause for admin
    (preserves the original query).
  - require_infra_access integration with platform_settings.
"""

from __future__ import annotations

import pytest
from app.services.authorization import (
    Permission,
    check_permission,
    filter_query_by_access,
    require_infra_access,
)
from fastapi import HTTPException

pytestmark = pytest.mark.service


def test_check_permission_is_case_sensitive():
    """Emails compared by string equality — confirm current behavior so
    a future canonicalisation change is intentional, not accidental."""
    user = {"sub": "Alice@example.com", "role": "user"}
    acl = {"owner": "alice@example.com", "editors": [], "viewers": []}
    # Currently FAILS — Alice@... != alice@... by string equality.
    # If the codebase ever canonicalises emails, this test flips and
    # we should update accordingly.
    with pytest.raises(HTTPException) as exc:
        check_permission(user, acl, Permission.VIEW)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_infra_access_admin_pass(db):
    """Admin role bypasses the infra-access allowlist."""
    user = await require_infra_access(
        user={"sub": "admin@x", "role": "admin"},
        db=db,
    )
    assert user["role"] == "admin"


@pytest.mark.asyncio
async def test_require_infra_access_no_settings_denies_non_admin(db):
    """When platform_settings has no infra_access row, non-admins are denied."""
    with pytest.raises(HTTPException) as exc:
        await require_infra_access(
            user={"sub": "u@x", "role": "user"},
            db=db,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_infra_access_user_in_allowlist_passes(db):
    """User in the allowlist passes."""
    from app.models.platform_settings import PlatformSettings

    db.add(
        PlatformSettings(
            key="infra_access",
            value={"emails": ["allowed@x"]},
        )
    )
    await db.commit()

    user = await require_infra_access(
        user={"sub": "allowed@x", "role": "user"},
        db=db,
    )
    assert user["sub"] == "allowed@x"


def test_filter_query_by_access_admin_returns_original_query():
    """Admin path returns the query untouched."""
    from app.models.orchestrator import Lab
    from sqlalchemy import select

    q = select(Lab)
    result = filter_query_by_access(q, Lab, {"sub": "a@x", "role": "admin"})
    assert result is q  # identity — no where clause appended
