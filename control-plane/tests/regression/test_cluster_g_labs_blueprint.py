"""Cluster G — labs_blueprint export auth + system_prompt strip.

Original audit: `/labs/{id}/export` was anonymous and shipped each agent's
`system_prompt` in the payload (a system-wide prompt-leak vector).

Fix asserted here:
- Anonymous → 401 (HTTPBearer 401 or 403, both acceptable).
- Authenticated non-ACL user → 403 (check_permission EDIT).
- ACL editor → 200; payload contains zero non-empty `system_prompt` strings.
- Admin → 200; payload contains zero non-empty `system_prompt` strings.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.regression


@pytest.mark.asyncio
async def test_export_lab_anonymous_blocked(anonymous_client, lab_factory, admin_user):
    lab = await lab_factory(owner=admin_user)
    r = await anonymous_client.get(f"/api/v1/labs/{lab.id}/export")
    assert r.status_code in (401, 403), r.text


@pytest.mark.asyncio
async def test_export_lab_non_acl_user_403(user_client, lab_factory, admin_user):
    lab = await lab_factory(owner=admin_user)  # owned by admin, not regular_user
    r = await user_client.get(f"/api/v1/labs/{lab.id}/export")
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_export_lab_admin_strips_system_prompt(admin_client, lab_factory, admin_user, db):
    """Admin can export; every system_prompt in the payload is empty."""
    from uuid import uuid4
    from app.models.orchestrator import Lab, LabAgent

    lab = await lab_factory(
        owner=admin_user,
        orchestrator_prompt="SUPER SECRET ORCHESTRATOR PROMPT — DO NOT LEAK",
    )
    # Insert an agent whose system_prompt is the canary.
    db.add(LabAgent(
        id=uuid4(), lab_id=lab.id, name="canary",
        system_prompt="SUPER SECRET AGENT PROMPT — DO NOT LEAK",
    ))
    await db.commit()

    r = await admin_client.get(f"/api/v1/labs/{lab.id}/export")
    assert r.status_code == 200, r.text
    body = r.json()
    # Orchestrator prompt zeroed.
    assert body["lab"]["orchestrator"]["prompt"] == ""
    # Every agent prompt zeroed.
    for agent in body["lab"]["agents"]:
        assert agent["system_prompt"] == "", (
            f"agent {agent['name']} still has a non-empty system_prompt — "
            "cluster G regression"
        )
    # Sanity: the canary string must not appear anywhere in the response.
    raw = r.text
    assert "SUPER SECRET AGENT PROMPT" not in raw
    assert "SUPER SECRET ORCHESTRATOR PROMPT" not in raw


@pytest.mark.asyncio
async def test_export_lab_editor_can_export(make_client, lab_factory, admin_user, editor_user):
    lab = await lab_factory(owner=admin_user, editors=[editor_user])
    client = await make_client(editor_user)
    r = await client.get(f"/api/v1/labs/{lab.id}/export")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_export_lab_viewer_denied_edit_perm(make_client, lab_factory, admin_user, viewer_user):
    """Viewer has VIEW rights but not EDIT — export demands EDIT."""
    lab = await lab_factory(owner=admin_user, viewers=[viewer_user])
    client = await make_client(viewer_user)
    r = await client.get(f"/api/v1/labs/{lab.id}/export")
    assert r.status_code == 403, r.text
