"""P06 + A03 — cross-tenant scan gates.

P06 — LabAgentRepository.get_all + TradingRepo.get_portfolio_pnl
      previously returned every row across every lab. Fix: optional
      user / lab_id filter scoped at the SQL layer.

A03 — LabMemoryRepository.get_all_memories is the shared-memory leak
      path. Fix: keyword-only contract requiring caller_lab_id +
      share_memory_confirmed=True. Calling without confirmation raises.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from app.models.orchestrator import Lab, LabAgent, LabMemory
from app.repositories.lab_repo import LabAgentRepository, LabMemoryRepository

pytestmark = pytest.mark.repo


# ── P06 — LabAgentRepository.get_all user filter ──────────────────


@pytest.mark.asyncio
async def test_lab_agent_get_all_no_user_returns_everything(db, lab_factory, admin_user):
    """Legacy path: no `user` arg → admin-equivalent (used by the
    still-unauthed /labs/agents/library route)."""
    lab1 = await lab_factory(owner=admin_user, name="l1")
    lab2 = await lab_factory(owner=admin_user, name="l2")
    db.add_all(
        [
            LabAgent(id=uuid.uuid4(), lab_id=lab1.id, name="a1"),
            LabAgent(id=uuid.uuid4(), lab_id=lab2.id, name="a2"),
        ]
    )
    await db.commit()
    rows = await LabAgentRepository(db).get_all()
    assert {a.name for a in rows} == {"a1", "a2"}


@pytest.mark.asyncio
async def test_lab_agent_get_all_admin_user_returns_everything(db, lab_factory, admin_user):
    lab1 = await lab_factory(owner=admin_user, name="l1")
    lab2 = await lab_factory(owner=admin_user, name="l2")
    db.add_all(
        [
            LabAgent(id=uuid.uuid4(), lab_id=lab1.id, name="a1"),
            LabAgent(id=uuid.uuid4(), lab_id=lab2.id, name="a2"),
        ]
    )
    await db.commit()
    rows = await LabAgentRepository(db).get_all(user=admin_user)
    assert {a.name for a in rows} == {"a1", "a2"}


@pytest.mark.asyncio
async def test_lab_agent_get_all_user_sees_only_accessible_labs(
    db,
    lab_factory,
    admin_user,
    regular_user,
):
    mine = await lab_factory(owner=regular_user, name="mine")
    not_mine = await lab_factory(owner=admin_user, name="not-mine")
    db.add_all(
        [
            LabAgent(id=uuid.uuid4(), lab_id=mine.id, name="visible"),
            LabAgent(id=uuid.uuid4(), lab_id=not_mine.id, name="hidden"),
        ]
    )
    await db.commit()
    rows = await LabAgentRepository(db).get_all(user=regular_user)
    assert {a.name for a in rows} == {"visible"}


# ── P06 — TradingRepo.get_portfolio_pnl lab_id filter ─────────────


@pytest.mark.asyncio
async def test_portfolio_pnl_scoped_by_lab(db, admin_user, lab_factory):
    from app.models.trading import TradingPosition
    from app.repositories.trading_repo import TradingRepo

    lab_a = await lab_factory(owner=admin_user, name="lab-a")
    lab_b = await lab_factory(owner=admin_user, name="lab-b")
    db.add_all(
        [
            TradingPosition(
                id=uuid.uuid4(),
                wallet_address="0xaa",
                chain="eth",
                token_address="0x1",
                token_symbol="ALPHA",
                amount_raw=Decimal(10**18),  # 1.0 ALPHA at 18 decimals
                token_decimals=18,
                entry_price_usd=Decimal("100"),
                status="open",
                lab_id=lab_a.id,
            ),
            TradingPosition(
                id=uuid.uuid4(),
                wallet_address="0xbb",
                chain="eth",
                token_address="0x2",
                token_symbol="BETA",
                amount_raw=Decimal(2 * 10**18),  # 2.0 BETA at 18 decimals
                token_decimals=18,
                entry_price_usd=Decimal("50"),
                status="open",
                lab_id=lab_b.id,
            ),
        ]
    )
    await db.commit()

    repo = TradingRepo(db)
    # Without lab_id → both positions (admin/operator path).
    pnl = await repo.get_portfolio_pnl()
    assert pnl["position_count"] == 2

    # With lab_id → only that lab's positions.
    pnl_a = await repo.get_portfolio_pnl(lab_id=lab_a.id)
    assert pnl_a["position_count"] == 1
    assert pnl_a["positions"][0]["token_symbol"] == "ALPHA"


# ── A03 — get_all_memories contract ───────────────────────────────


@pytest.mark.asyncio
async def test_get_all_memories_refuses_without_share_memory_confirmation(
    db,
    lab_factory,
    admin_user,
):
    """A03 (shipped): caller must explicitly confirm share_memory."""
    lab = await lab_factory(owner=admin_user)
    repo = LabMemoryRepository(db)
    with pytest.raises(PermissionError) as exc:
        await repo.get_all_memories(
            caller_lab_id=lab.id,
            share_memory_confirmed=False,
        )
    assert "share_memory" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_get_all_memories_succeeds_with_confirmation(
    db,
    lab_factory,
    admin_user,
):
    """A03: with both contract fields, the call goes through."""
    lab1 = await lab_factory(owner=admin_user, name="l1")
    lab2 = await lab_factory(owner=admin_user, name="l2")
    db.add_all(
        [
            LabMemory(
                id=uuid.uuid4(),
                lab_id=lab1.id,
                scope="lab",
                key="k1",
                content="lab1-memory",
            ),
            LabMemory(
                id=uuid.uuid4(),
                lab_id=lab2.id,
                scope="lab",
                key="k2",
                content="lab2-memory",
            ),
        ]
    )
    await db.commit()
    repo = LabMemoryRepository(db)
    rows = await repo.get_all_memories(
        caller_lab_id=lab1.id,
        share_memory_confirmed=True,
        limit=10,
    )
    contents = {m.content for m in rows}
    assert contents == {"lab1-memory", "lab2-memory"}


def test_get_all_memories_signature_keyword_only():
    """A03: caller_lab_id + share_memory_confirmed must be keyword-only
    so a positional-args refactor can't silently drop the guard."""
    import inspect

    sig = inspect.signature(LabMemoryRepository.get_all_memories)
    params = sig.parameters
    assert params["caller_lab_id"].kind == inspect.Parameter.KEYWORD_ONLY
    assert params["share_memory_confirmed"].kind == inspect.Parameter.KEYWORD_ONLY
