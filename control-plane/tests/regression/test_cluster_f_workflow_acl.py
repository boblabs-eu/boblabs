"""Cluster F — workflow per-row ACL.

Workflows previously had only the infra-access gate (an allowlist of
emails). Every infra user could CRUD every workflow. The fix adds a
per-workflow ACL JSONB and route-level check_permission.

For non-admin users to even reach the route they must be in the
infra-access allowlist. We seed `platform_settings.infra_access` with
the regular/editor users for these tests.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.regression


@pytest.fixture(autouse=True)
async def _grant_infra_access(db, regular_user, editor_user, viewer_user, other_user):
    """Add all the test users to the infra_access allowlist so they
    pass the router-level dep; per-workflow ACL is what we're testing."""
    from app.models.platform_settings import PlatformSettings

    db.add(PlatformSettings(
        key="infra_access",
        value={"emails": [
            regular_user["sub"],
            editor_user["sub"],
            viewer_user["sub"],
            other_user["sub"],
        ]},
    ))
    await db.commit()


async def _create_workflow_as_admin(client, name="wf1") -> str:
    r = await client.post("/api/v1/workflows", json={
        "name": name,
        "description": "x",
        "steps": [],
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_anonymous_blocked_on_workflows(anonymous_client):
    r = await anonymous_client.get("/api/v1/workflows")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_admin_creates_workflow_and_user_cannot_view(
    admin_client, make_client, regular_user,
):
    wf_id = await _create_workflow_as_admin(admin_client, name="admin-only")
    client = await make_client(regular_user)
    r = await client.get(f"/api/v1/workflows/{wf_id}")
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_user_sees_only_owned_workflows_in_list(
    admin_client, make_client, regular_user, db,
):
    """list_workflows filters by ACL for non-admin callers."""
    await _create_workflow_as_admin(admin_client, name="admin-wf")
    # Insert a second workflow owned by regular_user directly via DB
    from app.models.workflow import Workflow
    own = Workflow(
        id=uuid.uuid4(),
        name="user-wf",
        description="",
        definition={},
        acl={"owner": regular_user["sub"], "editors": [], "viewers": []},
    )
    db.add(own)
    await db.commit()

    client = await make_client(regular_user)
    r = await client.get("/api/v1/workflows")
    assert r.status_code == 200, r.text
    names = {wf["name"] for wf in r.json()}
    assert names == {"user-wf"}, names


@pytest.mark.asyncio
async def test_editor_can_update_but_outsider_cannot(
    db, make_client, regular_user, editor_user, other_user,
):
    from app.models.workflow import Workflow
    wf = Workflow(
        id=uuid.uuid4(),
        name="shared-wf",
        description="",
        definition={},
        acl={"owner": regular_user["sub"], "editors": [editor_user["sub"]], "viewers": []},
    )
    db.add(wf)
    await db.commit()
    wf_id = str(wf.id)

    editor_client = await make_client(editor_user)
    r = await editor_client.put(f"/api/v1/workflows/{wf_id}", json={
        "name": "renamed-by-editor", "description": "", "steps": [],
    })
    assert r.status_code == 200, r.text

    outsider_client = await make_client(other_user)
    r = await outsider_client.put(f"/api/v1/workflows/{wf_id}", json={
        "name": "should-not-take", "description": "", "steps": [],
    })
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_only_owner_or_admin_can_delete(
    db, make_client, admin_client, regular_user, editor_user,
):
    from app.models.workflow import Workflow
    wf = Workflow(
        id=uuid.uuid4(),
        name="del-test",
        description="",
        definition={},
        acl={"owner": regular_user["sub"], "editors": [editor_user["sub"]], "viewers": []},
    )
    db.add(wf)
    await db.commit()
    wf_id = str(wf.id)

    editor_client = await make_client(editor_user)
    r = await editor_client.delete(f"/api/v1/workflows/{wf_id}")
    assert r.status_code == 403, r.text  # editor doesn't get DELETE

    owner_client = await make_client(regular_user)
    r = await owner_client.delete(f"/api/v1/workflows/{wf_id}")
    assert r.status_code == 204, r.text
