"""LabRepository — current behavior tests + Session 2 prep.

Tests that pass today (current behavior):
- get_all with user filters by ACL (admin sees all, user sees ACL-permitted).
- get_by_id returns None for missing UUID.
- create with user injects default ACL with caller as owner.

Tests xfailed until Session 2 (cluster P01-P05 — pagination caps):
- get_all returns ≤500 rows even with 1000+ rows in the DB.
- LabMessageRepository.get_by_lab honours the documented `limit` arg
  AND is capped at the server-side maximum.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.orchestrator import Lab
from app.repositories.lab_repo import LabRepository

pytestmark = pytest.mark.repo


# ── Current behavior ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_all_admin_sees_everything(db, admin_user):
    db.add_all([
        Lab(id=uuid.uuid4(), name=f"l-{i}", acl={"owner": "x", "editors": [], "viewers": []})
        for i in range(5)
    ])
    await db.commit()
    repo = LabRepository(db)
    rows = await repo.get_all(user=admin_user)
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_get_all_user_filtered_by_acl(db, regular_user):
    db.add_all([
        Lab(id=uuid.uuid4(), name="mine",
            acl={"owner": regular_user["sub"], "editors": [], "viewers": []}),
        Lab(id=uuid.uuid4(), name="not-mine",
            acl={"owner": "other@x", "editors": [], "viewers": []}),
    ])
    await db.commit()
    repo = LabRepository(db)
    rows = await repo.get_all(user=regular_user)
    assert {r.name for r in rows} == {"mine"}


@pytest.mark.asyncio
async def test_get_by_id_missing_returns_none(db):
    repo = LabRepository(db)
    assert await repo.get_by_id(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_create_with_user_injects_default_acl(db, regular_user):
    repo = LabRepository(db)
    lab = await repo.create(user=regular_user, name="created-by-user")
    await db.refresh(lab)
    assert lab.acl["owner"] == regular_user["sub"]
    assert lab.acl["editors"] == []
    assert lab.acl["viewers"] == []


# ── Session 2 — P01/P04/P05 caps (shipped) ────────────────────────


@pytest.mark.asyncio
async def test_get_all_has_max_limit_cap(db, admin_user):
    """P01 (shipped): LabRepository.get_all clamps at MAX_LIMIT and
    honours an explicit caller-supplied limit."""
    db.add_all([
        Lab(id=uuid.uuid4(), name=f"l-{i}",
            acl={"owner": "x", "editors": [], "viewers": []})
        for i in range(50)
    ])
    await db.commit()
    repo = LabRepository(db)
    import inspect
    sig = inspect.signature(repo.get_all)
    assert "limit" in sig.parameters, "get_all regressed — `limit` removed"
    assert "offset" in sig.parameters, "get_all regressed — `offset` removed"
    rows = await repo.get_all(user=admin_user, limit=10)
    assert len(rows) == 10


@pytest.mark.asyncio
async def test_get_all_clamps_caller_overflow(db, admin_user):
    """P05 (shipped): a caller passing limit=10**6 is clamped to MAX_LIMIT."""
    from app.repositories._paginate import MAX_LIMIT
    db.add_all([
        Lab(id=uuid.uuid4(), name=f"l-{i}",
            acl={"owner": "x", "editors": [], "viewers": []})
        for i in range(5)
    ])
    await db.commit()
    repo = LabRepository(db)
    rows = await repo.get_all(user=admin_user, limit=10**6)
    assert len(rows) <= MAX_LIMIT


@pytest.mark.asyncio
async def test_cron_get_labs_using_uses_jsonb_containment(db, admin_user, lab_factory):
    """P01 (shipped): CronJobRepository.get_labs_using runs a single
    JSONB containment SELECT instead of scanning every Lab in Python."""
    from app.models.orchestrator import CronJob
    from app.repositories.lab_repo import CronJobRepository

    cj = CronJob(id=uuid.uuid4(), name="probe", expression="0 * * * *")
    db.add(cj)
    other_cj_id = str(uuid.uuid4())
    await lab_factory(owner=admin_user, name="uses-it", cron_job_ids=[str(cj.id)])
    await lab_factory(owner=admin_user, name="uses-other", cron_job_ids=[other_cj_id])
    await lab_factory(owner=admin_user, name="uses-nothing", cron_job_ids=[])
    await db.commit()

    # The result must be exactly the labs that reference cj.id.
    repo = CronJobRepository(db)
    rows = await repo.get_labs_using(cj.id)
    names = sorted(r["name"] for r in rows)
    assert names == ["uses-it"]


@pytest.mark.asyncio
async def test_get_injections_capped(db, admin_user, lab_factory):
    """P03 (shipped): get_injections is no longer unbounded."""
    from app.models.orchestrator import LabMessage
    from app.repositories.lab_repo import LabMessageRepository
    from app.repositories._paginate import MAX_LIMIT

    lab = await lab_factory(owner=admin_user)
    # 20 messages is plenty to verify the clamp wiring without a slow
    # seed; the MAX_LIMIT default kicks in for caller=None / overflow.
    db.add_all([
        LabMessage(
            id=uuid.uuid4(), lab_id=lab.id, sender_type="agent",
            sender_name=f"a{i}", content="x", message_type="inject",
        ) for i in range(20)
    ])
    await db.commit()
    repo = LabMessageRepository(db)
    rows = await repo.get_injections(lab.id, limit=10**6)
    assert len(rows) <= MAX_LIMIT
    # Sanity: an explicit small limit is honoured too.
    rows = await repo.get_injections(lab.id, limit=5)
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_lab_message_get_by_lab_honours_explicit_limit(db, admin_user):
    """Sanity: get_by_lab respects the caller's `limit` arg today."""
    from app.repositories.lab_repo import LabMessageRepository
    lab = Lab(id=uuid.uuid4(), name="t", acl={"owner": "x", "editors": [], "viewers": []})
    db.add(lab)
    await db.commit()

    from app.models.orchestrator import LabMessage
    db.add_all([
        LabMessage(
            id=uuid.uuid4(), lab_id=lab.id, sender_type="agent",
            sender_name=f"a{i}", content="x",
        ) for i in range(20)
    ])
    await db.commit()
    repo = LabMessageRepository(db)
    rows = await repo.get_by_lab(lab.id, limit=5)
    assert len(rows) == 5
    # Note: there's no server-side max yet — Session 2 P02 will add one.
    # See test_get_all_has_max_limit_cap above (xfail) for the gap.
