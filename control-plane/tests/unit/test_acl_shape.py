"""ACL JSONB shape tests.

The current schema treats `acl` as an arbitrary JSONB blob — there is
no DB-level CHECK constraint or app-level validator. Several tests in
this file are therefore marked `xfail(strict=False)`: they document the
shape we WILL enforce in Phase 5 Session 3 (D04 — ACL JSONB shape
CHECK in 0009_workflow_step_order_unique.py). Once that migration
lands, the xfails should start passing and the markers can be removed.

Tests without xfail markers cover existing behavior (default ACL shape,
owner-only ACL works end-to-end).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.orchestrator import Lab
from app.services.authorization import get_default_acl


# ── Current behavior (passing today) ───────────────────────────────


@pytest.mark.asyncio
async def test_default_acl_shape_round_trips(db, regular_user, lab_factory):
    lab = await lab_factory(owner=regular_user)
    # Re-read from DB to confirm Postgres preserved the JSONB shape.
    fresh = (await db.execute(select(Lab).where(Lab.id == lab.id))).scalar_one()
    assert fresh.acl == {
        "owner": regular_user["sub"],
        "editors": [],
        "viewers": [],
    }


@pytest.mark.asyncio
async def test_acl_with_editors_and_viewers_round_trips(
    db, regular_user, editor_user, viewer_user, lab_factory,
):
    lab = await lab_factory(
        owner=regular_user, editors=[editor_user], viewers=[viewer_user],
    )
    fresh = (await db.execute(select(Lab).where(Lab.id == lab.id))).scalar_one()
    assert fresh.acl["owner"] == regular_user["sub"]
    assert fresh.acl["editors"] == [editor_user["sub"]]
    assert fresh.acl["viewers"] == [viewer_user["sub"]]


@pytest.mark.asyncio
async def test_get_default_acl_used_by_repo_layer(db, regular_user):
    """get_default_acl is the canonical shape — confirm it's the same
    structure tests assert against above."""
    acl = get_default_acl(regular_user["sub"])
    lab = Lab(id=uuid.uuid4(), name="t", acl=acl)
    db.add(lab)
    await db.commit()
    fresh = (await db.execute(select(Lab).where(Lab.id == lab.id))).scalar_one()
    assert fresh.acl == acl


# ── D04 (shipped in Session 3) — ck_<table>_acl_shape ─────────────


@pytest.mark.asyncio
async def test_acl_with_non_string_owner_rejected(db):
    """D04 (shipped): `owner` must be a string email."""
    lab = Lab(id=uuid.uuid4(), name="bad-owner",
              acl={"owner": 12345, "editors": [], "viewers": []})
    db.add(lab)
    with pytest.raises((IntegrityError, DBAPIError)):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_acl_with_non_list_editors_rejected(db):
    """D04 (shipped): `editors` and `viewers` must be JSON arrays."""
    lab = Lab(id=uuid.uuid4(), name="bad-editors",
              acl={"owner": "x@x", "editors": "not-a-list", "viewers": []})
    db.add(lab)
    with pytest.raises((IntegrityError, DBAPIError)):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_acl_missing_required_keys_rejected(db):
    """D04 (shipped): `owner` is required."""
    lab = Lab(id=uuid.uuid4(), name="missing-owner",
              acl={"editors": [], "viewers": []})
    db.add(lab)
    with pytest.raises((IntegrityError, DBAPIError)):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_acl_extra_keys_allowed(db, admin_user):
    """D04 — extra keys are intentionally allowed.

    The codebase already uses ``acl->>'tag'`` to mark consumer-app /
    showroom / agent-instance labs. The CHECK constraint enforces the
    required shape but does NOT forbid extra top-level keys.
    """
    lab = Lab(
        id=uuid.uuid4(), name="extra-keys",
        acl={"owner": admin_user["sub"], "editors": [], "viewers": [],
             "tag": "agent_instance"},
    )
    db.add(lab)
    await db.commit()  # must succeed
    await db.refresh(lab)
    assert lab.acl["tag"] == "agent_instance"


# ── Defense: missing-key ACL denies non-admin VIEW ────────────────


@pytest.mark.asyncio
async def test_empty_dict_acl_denies_non_admin():
    """check_permission against an empty `{}` ACL must deny every
    non-admin permission (no owner key, no editors, no viewers)."""
    from app.services.authorization import Permission, check_permission
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        check_permission({"sub": "anyone@x", "role": "user"},
                         {}, Permission.VIEW)
    assert exc.value.status_code == 403
