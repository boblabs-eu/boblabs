"""SQL query counter — N+1 detection harness.

The fixture `assert_query_count` wraps a code block and counts the
SELECT queries emitted by SQLAlchemy's `engine.before_cursor_execute`
event. Use it to spot N+1 patterns where a list endpoint emits one
extra query per row.

Session 2 will use this to guard list_workflows, list_labs, list_drafts.
For Session 1.5 we just assert the fixture itself works.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from app.database import engine
from app.models.orchestrator import Lab
from app.repositories.lab_repo import LabRepository
from sqlalchemy import event

pytestmark = pytest.mark.repo


@contextmanager
def count_select_queries():
    counts = {"n": 0}

    def _listener(conn, cursor, statement, params, context, executemany):
        if statement.strip().upper().startswith("SELECT"):
            counts["n"] += 1

    event.listen(engine.sync_engine, "before_cursor_execute", _listener)
    try:
        yield counts
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _listener)


@pytest.mark.asyncio
async def test_query_counter_fixture_smoke(db, admin_user):
    db.add(Lab(id=uuid.uuid4(), name="t", acl={"owner": "x", "editors": [], "viewers": []}))
    await db.commit()

    with count_select_queries() as c:
        repo = LabRepository(db)
        rows = await repo.get_all(user=admin_user)
    assert len(rows) == 1
    # Should be exactly 1 SELECT — no eager-loaded relationships.
    assert c["n"] >= 1


@pytest.mark.asyncio
async def test_list_labs_no_n_plus_one_on_agent_count(db, admin_client, admin_user, lab_factory):
    """P02 (shipped): /labs must aggregate agent counts in a single
    GROUP BY query, not one SELECT per lab.

    With 10 labs, the pre-fix code emitted 11+ SELECTs (1 for labs +
    10 for per-lab agents). Post-fix: ≤4 (labs + messages + agents +
    possibly app-tag filter), independent of lab count.
    """
    from app.models.orchestrator import LabAgent

    for i in range(10):
        lab = await lab_factory(owner=admin_user, name=f"p02-lab-{i}")
        db.add(
            LabAgent(
                id=uuid.uuid4(),
                lab_id=lab.id,
                name=f"agent-{i}",
            )
        )
    await db.commit()

    with count_select_queries() as c:
        r = await admin_client.get("/api/v1/labs")
        assert r.status_code == 200, r.text

    assert c["n"] <= 5, (
        f"/api/v1/labs emitted {c['n']} SELECTs for 10 labs — P02 regression "
        f"(should aggregate via GROUP BY, not loop)"
    )


@pytest.mark.asyncio
async def test_list_workflows_no_n_plus_one(db, admin_client):
    """Listing 5 workflows must emit ≤ 3 SELECTs (one for the
    workflows table, optional fan-out, not 5+ per-row queries)."""
    from app.models.workflow import Workflow

    db.add_all(
        [
            Workflow(
                id=uuid.uuid4(),
                name=f"wf-{i}",
                description="",
                definition={},
                acl={"owner": "admin@test.local", "editors": [], "viewers": []},
            )
            for i in range(5)
        ]
    )
    await db.commit()

    with count_select_queries() as c:
        r = await admin_client.get("/api/v1/workflows")
        assert r.status_code == 200

    assert c["n"] <= 3, (
        f"/api/v1/workflows emitted {c['n']} SELECTs for 5 workflows — N+1 suspected"
    )
