"""Wave 4 O.2 — outreach routes enforce per-lab ACL.

Pre-fix: every authenticated user could list/get/edit/reject/send every
draft across every lab. Even an editor on a single lab could see other
labs' drafts.

Post-fix:
- list_drafts is scoped to labs the caller can VIEW (admin sees all).
- get_draft requires VIEW; edit/reject/send require EDIT.
- 404 on missing lab (don't leak existence to an outsider).

Tests assert behavior, not source — we hit the actual HTTP routes
against real labs.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression


@pytest.fixture
def lab_resources_root(tmp_path, monkeypatch):
    """Override LAB_RESOURCES_ROOT to a tmp dir for the test."""
    from app.api.routes import labs as labs_mod
    from app.api.routes import outreach as outreach_mod

    root = tmp_path / "lab_resources"
    root.mkdir()
    monkeypatch.setattr(labs_mod, "LAB_RESOURCES_ROOT", root)
    monkeypatch.setattr(outreach_mod, "LAB_RESOURCES_ROOT", root)
    return root


def _write_draft(root: Path, lab_id: str, filename: str, to: str = "x@y", subject: str = "hi"):
    drafts = root / lab_id / "output" / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    (drafts / filename).write_text(
        f"---\nto: {to}\nsubject: {subject}\n---\n\nHello\n", encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_list_drafts_admin_sees_all(
    admin_client,
    lab_factory,
    lab_resources_root,
    admin_user,
    regular_user,
):
    lab1 = await lab_factory(owner=admin_user)
    lab2 = await lab_factory(owner=regular_user)
    _write_draft(lab_resources_root, str(lab1.id), "d1.md")
    _write_draft(lab_resources_root, str(lab2.id), "d2.md")

    r = await admin_client.get("/api/v1/outreach/drafts?status_filter=pending")
    assert r.status_code == 200, r.text
    filenames = {d["filename"] for d in r.json()}
    assert filenames == {"d1.md", "d2.md"}


@pytest.mark.asyncio
async def test_list_drafts_user_only_sees_accessible_labs(
    make_client,
    lab_factory,
    lab_resources_root,
    admin_user,
    regular_user,
):
    mine = await lab_factory(owner=regular_user)
    not_mine = await lab_factory(owner=admin_user)
    _write_draft(lab_resources_root, str(mine.id), "mine.md")
    _write_draft(lab_resources_root, str(not_mine.id), "other.md")

    client = await make_client(regular_user)
    r = await client.get("/api/v1/outreach/drafts?status_filter=pending")
    assert r.status_code == 200, r.text
    filenames = {d["filename"] for d in r.json()}
    assert filenames == {"mine.md"}, filenames


@pytest.mark.asyncio
async def test_get_draft_requires_view_permission(
    make_client,
    lab_factory,
    lab_resources_root,
    admin_user,
    other_user,
):
    lab = await lab_factory(owner=admin_user)
    _write_draft(lab_resources_root, str(lab.id), "x.md")
    client = await make_client(other_user)
    r = await client.get(f"/api/v1/outreach/drafts/{lab.id}/x.md")
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_get_draft_viewer_can_read(
    make_client,
    lab_factory,
    lab_resources_root,
    admin_user,
    viewer_user,
):
    lab = await lab_factory(owner=admin_user, viewers=[viewer_user])
    _write_draft(lab_resources_root, str(lab.id), "x.md")
    client = await make_client(viewer_user)
    r = await client.get(f"/api/v1/outreach/drafts/{lab.id}/x.md")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_edit_draft_viewer_denied_edit(
    make_client,
    lab_factory,
    lab_resources_root,
    admin_user,
    viewer_user,
):
    lab = await lab_factory(owner=admin_user, viewers=[viewer_user])
    _write_draft(lab_resources_root, str(lab.id), "x.md")
    client = await make_client(viewer_user)
    r = await client.patch(
        f"/api/v1/outreach/drafts/{lab.id}/x.md",
        json={"subject": "hacked"},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_edit_draft_editor_can_edit(
    make_client,
    lab_factory,
    lab_resources_root,
    admin_user,
    editor_user,
):
    lab = await lab_factory(owner=admin_user, editors=[editor_user])
    _write_draft(lab_resources_root, str(lab.id), "x.md")
    client = await make_client(editor_user)
    r = await client.patch(
        f"/api/v1/outreach/drafts/{lab.id}/x.md",
        json={"subject": "new subject"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["subject"] == "new subject"
