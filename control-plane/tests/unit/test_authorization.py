"""Unit tests for app.services.authorization.

Covers:
- check_permission across every ACL shape (owner, editors, viewers, missing keys)
- check_permission honours admin bypass + None acl rejection
- filter_query_by_access: admin sees all, user sees only ACL-permitted rows
  (PostgreSQL JSONB operators — requires real DB)
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.orchestrator import Lab
from app.services.authorization import (
    Permission,
    check_permission,
    filter_query_by_access,
    get_default_acl,
)


# ── check_permission — admin bypass ────────────────────────────────


def test_admin_bypasses_all_permissions():
    admin = {"sub": "admin@x", "role": "admin"}
    # Even with a None ACL or missing email, admin passes every permission.
    for perm in Permission:
        check_permission(admin, None, perm)
        check_permission(admin, {}, perm)
        check_permission(admin, {"owner": "someone-else@x"}, perm)


# ── check_permission — owner has all rights ────────────────────────


def test_owner_has_all_permissions():
    user = {"sub": "owner@x", "role": "user"}
    acl = {"owner": "owner@x", "editors": [], "viewers": []}
    for perm in Permission:
        check_permission(user, acl, perm)


# ── check_permission — editors ─────────────────────────────────────


def test_editor_can_view_and_edit():
    user = {"sub": "editor@x", "role": "user"}
    acl = {"owner": "owner@x", "editors": ["editor@x"], "viewers": []}
    check_permission(user, acl, Permission.VIEW)
    check_permission(user, acl, Permission.EDIT)


def test_editor_cannot_delete_or_manage():
    user = {"sub": "editor@x", "role": "user"}
    acl = {"owner": "owner@x", "editors": ["editor@x"], "viewers": []}
    with pytest.raises(HTTPException) as exc:
        check_permission(user, acl, Permission.DELETE)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        check_permission(user, acl, Permission.MANAGE)
    assert exc.value.status_code == 403


# ── check_permission — viewers ─────────────────────────────────────


def test_viewer_can_view_only():
    user = {"sub": "viewer@x", "role": "user"}
    acl = {"owner": "owner@x", "editors": [], "viewers": ["viewer@x"]}
    check_permission(user, acl, Permission.VIEW)
    for forbidden in (Permission.EDIT, Permission.DELETE, Permission.MANAGE):
        with pytest.raises(HTTPException) as exc:
            check_permission(user, acl, forbidden)
        assert exc.value.status_code == 403


# ── check_permission — outsiders denied ────────────────────────────


def test_unrelated_user_denied_on_all_permissions():
    user = {"sub": "outsider@x", "role": "user"}
    acl = {"owner": "owner@x", "editors": ["editor@x"], "viewers": ["viewer@x"]}
    for perm in Permission:
        with pytest.raises(HTTPException) as exc:
            check_permission(user, acl, perm)
        assert exc.value.status_code == 403


def test_anonymous_user_denied():
    """sub missing or empty → treated as no match."""
    user = {"role": "user"}  # no sub
    acl = {"owner": "owner@x", "editors": [], "viewers": []}
    with pytest.raises(HTTPException):
        check_permission(user, acl, Permission.VIEW)


# ── check_permission — None ACL ────────────────────────────────────


def test_none_acl_denies_non_admin():
    user = {"sub": "u@x", "role": "user"}
    with pytest.raises(HTTPException) as exc:
        check_permission(user, None, Permission.VIEW)
    assert exc.value.status_code == 403


# ── check_permission — missing ACL keys ────────────────────────────


def test_acl_with_missing_editors_key_does_not_crash():
    user = {"sub": "owner@x", "role": "user"}
    acl = {"owner": "owner@x"}  # no editors, no viewers
    check_permission(user, acl, Permission.VIEW)
    check_permission(user, acl, Permission.EDIT)


def test_acl_with_missing_owner_key_denies():
    user = {"sub": "u@x", "role": "user"}
    acl = {"editors": [], "viewers": []}  # no owner field
    with pytest.raises(HTTPException):
        check_permission(user, acl, Permission.VIEW)


# ── get_default_acl ────────────────────────────────────────────────


def test_get_default_acl_shape():
    acl = get_default_acl("foo@bar")
    assert acl == {"owner": "foo@bar", "editors": [], "viewers": []}


# ── filter_query_by_access — needs real Postgres ───────────────────


@pytest.mark.asyncio
async def test_filter_query_by_access_admin_sees_all(db, admin_user, regular_user):
    # Create two labs owned by different non-admin users.
    db.add_all([
        Lab(id=uuid.uuid4(), name="a", acl={"owner": "u1@x", "editors": [], "viewers": []}),
        Lab(id=uuid.uuid4(), name="b", acl={"owner": "u2@x", "editors": [], "viewers": []}),
    ])
    await db.commit()

    q = filter_query_by_access(select(Lab), Lab, admin_user)
    rows = (await db.execute(q)).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_filter_query_by_access_user_sees_owned_only(db, regular_user):
    db.add_all([
        Lab(id=uuid.uuid4(), name="mine",
            acl={"owner": regular_user["sub"], "editors": [], "viewers": []}),
        Lab(id=uuid.uuid4(), name="not-mine",
            acl={"owner": "other@x", "editors": [], "viewers": []}),
    ])
    await db.commit()

    q = filter_query_by_access(select(Lab), Lab, regular_user)
    rows = (await db.execute(q)).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "mine"


@pytest.mark.asyncio
async def test_filter_query_by_access_user_sees_editor_rows(db, regular_user):
    db.add_all([
        Lab(id=uuid.uuid4(), name="editor-on-this",
            acl={"owner": "other@x", "editors": [regular_user["sub"]], "viewers": []}),
        Lab(id=uuid.uuid4(), name="not-mine",
            acl={"owner": "other@x", "editors": [], "viewers": []}),
    ])
    await db.commit()

    q = filter_query_by_access(select(Lab), Lab, regular_user)
    rows = (await db.execute(q)).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "editor-on-this"


@pytest.mark.asyncio
async def test_filter_query_by_access_user_sees_viewer_rows(db, viewer_user):
    db.add_all([
        Lab(id=uuid.uuid4(), name="viewer-on-this",
            acl={"owner": "other@x", "editors": [], "viewers": [viewer_user["sub"]]}),
        Lab(id=uuid.uuid4(), name="not-mine",
            acl={"owner": "other@x", "editors": [], "viewers": []}),
    ])
    await db.commit()

    q = filter_query_by_access(select(Lab), Lab, viewer_user)
    rows = (await db.execute(q)).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "viewer-on-this"


@pytest.mark.asyncio
async def test_filter_query_by_access_returns_empty_for_outsider(db, other_user):
    db.add(Lab(id=uuid.uuid4(), name="not-yours",
               acl={"owner": "x@x", "editors": ["y@x"], "viewers": ["z@x"]}))
    await db.commit()
    q = filter_query_by_access(select(Lab), Lab, other_user)
    rows = (await db.execute(q)).scalars().all()
    assert rows == []
