"""Session 4 — architecture + reliability regression suite.

Covers items A01 (1inch router allow-list), A02 (per-call tool
re-resolution introspection), A05 (Qdrant-first ordering), R03
(stop() awaits loop exit), R05 (per-tool wait_for stays in place),
R14 (recovery timeout + sweeper).
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.service


# ── A01 — 1inch router allow-list ──────────────────────────────────


def test_a01_allowlist_includes_known_routers():
    from app.services.trading_service import get_swap_router_allowlist
    eth = get_swap_router_allowlist("ethereum")
    # 1inch v6 + Uniswap V2 + Uniswap V3 all present, lowercase.
    assert "0x111111125421ca6dc452d289314280a0f8842a65" in eth
    assert "0x7a250d5630b4cf539739df2c5dacb4c659f2488d" in eth
    assert "0xe592427a0aece92de3edee1f18e0157c05861564" in eth


def test_a01_rejects_unknown_address():
    from app.services.trading_service import assert_swap_router_allowed
    with pytest.raises(ValueError) as exc:
        # Attacker contract that compromised-1inch might substitute in.
        assert_swap_router_allowed("ethereum", "0xdeadbeef00000000000000000000000000000000")
    assert "not on the allow-list" in str(exc.value)


def test_a01_rejects_empty_to():
    from app.services.trading_service import assert_swap_router_allowed
    with pytest.raises(ValueError):
        assert_swap_router_allowed("ethereum", "")


def test_a01_rejects_unknown_chain():
    from app.services.trading_service import assert_swap_router_allowed
    with pytest.raises(ValueError) as exc:
        assert_swap_router_allowed("solana", "0x111111125421ca6dc452d289314280a0f8842a65")
    assert "allow-list" in str(exc.value).lower()


def test_a01_accepts_known_router_case_insensitive():
    from app.services.trading_service import assert_swap_router_allowed
    # No raise.
    assert_swap_router_allowed("ethereum", "0x111111125421cA6dc452d289314280a0f8842A65")
    assert_swap_router_allowed("base", "0x4752BA5DBC23F44D87826276BF6FD6B1C372AD24")


def test_a01_tool_trading_calls_assert_before_estimate_and_send():
    """Source-level: the 1inch swap path must call assert_swap_router_allowed
    before estimate_and_send (i.e. before signing). A future refactor
    that drops the assert would fail this test."""
    from app.services.tools import tool_trading
    src = inspect.getsource(tool_trading)
    # Locate the assert call and the estimate_and_send call after it.
    assert "assert_swap_router_allowed" in src, (
        "tool_trading no longer references assert_swap_router_allowed — A01 regression"
    )
    # The assert must appear before the estimate_and_send call.
    a_pos = src.find("assert_swap_router_allowed(chain, tx_dict[\"to\"]")
    s_pos = src.find("estimate_and_send(chain, wallet, tx, gas_mult)")
    assert a_pos != -1 and s_pos != -1
    assert a_pos < s_pos, "A01 — assert_swap_router_allowed must run BEFORE estimate_and_send"


# ── A02 — re-resolve tools per call ────────────────────────────────


def test_a02_lab_runner_refreshes_agent_in_tool_loop():
    """Source-level: the agent tool-call while-loop refreshes the agent
    + re-resolves tools at the top of each body."""
    from app.services import lab_runner
    src = inspect.getsource(lab_runner)
    # The fix added `await db.refresh(agent)` inside the while body and
    # a comment block marked "A02".
    assert "# A02 — re-resolve the agent's allowed tool set" in src, (
        "lab_runner A02 comment is gone — re-resolution may have been removed"
    )
    assert "await db.refresh(agent)" in src
    assert "agent_normalized_tools = set(normalize_tool_names(agent_tools))" in src


# ── A05 — Qdrant-first ordering ────────────────────────────────────


def test_a05_create_collection_does_qdrant_before_db():
    """Source-level: ensure_qdrant_collection runs before collections.create."""
    from app.services import rag_service
    fn = rag_service.RagService.create_collection
    src = inspect.getsource(fn)
    qdrant_pos = src.find("_ensure_qdrant_collection")
    db_pos = src.find("await self.collections.create(")
    assert qdrant_pos != -1 and db_pos != -1
    assert qdrant_pos < db_pos, (
        "A05 — Qdrant create must precede DB row create; current ordering "
        "leaves an orphan DB row if Qdrant raises"
    )


def test_a05_create_collection_compensates_on_db_failure():
    """Source-level: the except branch must call delete_collection."""
    from app.services import rag_service
    fn = rag_service.RagService.create_collection
    src = inspect.getsource(fn)
    assert "delete_collection" in src, (
        "A05 — DB-create-failure branch no longer rolls back the Qdrant "
        "collection; orphan Qdrant state would accumulate on retries"
    )


# ── R03 — stop() awaits the loop ──────────────────────────────────


@pytest.mark.asyncio
async def test_r03_stop_waits_for_run_exit():
    """LabRunner.stop() blocks until run()'s finally fires."""
    from app.services.lab_runner import LabRunner

    runner = LabRunner(uuid.uuid4(), session_factory=None)  # type: ignore[arg-type]
    # Simulate a `run()` that takes 0.1s then exits.
    async def fake_run():
        await asyncio.sleep(0.05)
        runner._stopped.set()

    asyncio.create_task(fake_run())
    t0 = asyncio.get_event_loop().time()
    await runner.stop(wait_timeout=2.0)
    elapsed = asyncio.get_event_loop().time() - t0
    assert 0.04 <= elapsed <= 1.0, f"stop() returned in {elapsed:.3f}s — expected to await run() exit"


@pytest.mark.asyncio
async def test_r03_stop_times_out_cleanly_on_wedged_loop():
    """If run() never exits, stop() returns after wait_timeout without raising."""
    from app.services.lab_runner import LabRunner
    runner = LabRunner(uuid.uuid4(), session_factory=None)  # type: ignore[arg-type]
    # _stopped never gets set.
    await runner.stop(wait_timeout=0.1)  # no raise


@pytest.mark.asyncio
async def test_r03_stop_returns_immediately_if_already_stopped():
    from app.services.lab_runner import LabRunner
    runner = LabRunner(uuid.uuid4(), session_factory=None)  # type: ignore[arg-type]
    runner._stopped.set()
    t0 = asyncio.get_event_loop().time()
    await runner.stop(wait_timeout=10.0)
    elapsed = asyncio.get_event_loop().time() - t0
    assert elapsed < 0.05


# ── R05 — per-tool wait_for stays in place ────────────────────────


def test_r05_tool_executor_wraps_handler_in_wait_for():
    """ToolExecutor.execute must wrap the handler call in asyncio.wait_for
    so a hung tool can't block the lab loop forever."""
    from app.services import tool_executor
    src = inspect.getsource(tool_executor)
    assert "asyncio.wait_for" in src
    assert "timeout=effective_timeout" in src or "timeout=self.timeout_sec" in src
    # Specifically inside the execute method:
    execute_src = inspect.getsource(tool_executor.ToolExecutor.execute)
    assert "asyncio.wait_for" in execute_src, (
        "ToolExecutor.execute no longer wraps the handler call in wait_for — R05 regression"
    )


# ── R14 — recovery timeout + sweeper ──────────────────────────────


@pytest.mark.asyncio
async def test_r14_handle_report_times_out_recovery_and_clears_set():
    """If _recover wedges forever, _handle_report's wait_for fires and
    _recovering is cleared so the next round can retry."""
    from app.services.loop_detection.manager import LoopManager
    from app.services.loop_detection.base import LoopReport, LoopSignal
    import app.services.loop_detection.manager as mgr_mod

    lab_id = uuid.uuid4()
    mgr = LoopManager()
    mgr.configure(AsyncMock())

    # _recover never returns. Use patch to substitute on the instance.
    async def hung_recover(*args, **kwargs):
        await asyncio.sleep(60)

    mgr._recover = hung_recover  # type: ignore[method-assign]

    # Patch the module-level constant down to 0.05s so the test runs fast.
    with patch.object(mgr_mod, "RECOVERY_TIMEOUT_SEC", 0.05), \
         patch.object(mgr_mod, "ws_manager") as ws_mock:
        ws_mock.broadcast_to_clients = AsyncMock()
        report = LoopReport(
            detected=True, severity="red", score=99,
            signals=[LoopSignal(name="x", score=99, detail="y")],
            loop_message_ids=[],
        )
        await mgr._handle_report(lab_id, anti_loop_enabled=True, report=report)

    assert lab_id not in mgr._recovering, (
        "_recovering still pinned after timeout — R14 regression"
    )
    assert lab_id not in mgr._recovery_started_at


@pytest.mark.asyncio
async def test_r14_sweep_evicts_stale_entries():
    """sweep_stale_recoveries drops entries older than RECOVERY_TIMEOUT_SEC."""
    from app.services.loop_detection.manager import LoopManager, _now
    import app.services.loop_detection.manager as mgr_mod

    mgr = LoopManager()
    fresh = uuid.uuid4()
    stale = uuid.uuid4()
    mgr._recovering.update({fresh, stale})
    mgr._recovery_started_at[fresh] = _now()
    mgr._recovery_started_at[stale] = _now() - timedelta(seconds=600)

    with patch.object(mgr_mod, "RECOVERY_TIMEOUT_SEC", 60):
        evicted = await mgr.sweep_stale_recoveries()

    assert evicted == 1
    assert fresh in mgr._recovering
    assert stale not in mgr._recovering
