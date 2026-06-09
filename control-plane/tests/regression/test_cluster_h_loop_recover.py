"""Cluster H — LoopManager._recover handles runner.resume() failure.

Pre-fix: if runner.resume() raised AFTER the message DELETE, the lab
silently stayed paused and `_recovering` was never cleared, so all
future recovery attempts were no-ops.

Post-fix:
  - resume() failure broadcasts `lab.loop_recovery_failed` so the UI
    surfaces a banner.
  - `_recovering` is always cleared in `_handle_report` finally.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.services.loop_detection.base import LoopReport, LoopSignal
from app.services.loop_detection.manager import LoopManager

pytestmark = pytest.mark.regression


def _make_report():
    return LoopReport(
        detected=True,
        severity="red",
        score=99,
        signals=[LoopSignal(name="exact_repeat", score=99, detail="x3")],
        loop_message_ids=[],
    )


@pytest.mark.asyncio
async def test_recovering_set_cleared_after_resume_failure(db):
    """_recovering must be empty after _handle_report, even if resume fails."""
    from app.database import async_session

    lab_id = uuid.uuid4()
    mgr = LoopManager()
    mgr.configure(async_session)

    # Mock the runner so pause() succeeds and resume() raises.
    fake_runner = AsyncMock()
    fake_runner.pause = AsyncMock()
    fake_runner.resume = AsyncMock(side_effect=RuntimeError("simulated resume failure"))

    with (
        patch("app.services.lab_runner.get_runner", return_value=fake_runner),
        patch("app.services.loop_detection.manager.ws_manager") as ws_mock,
    ):
        ws_mock.broadcast_to_clients = AsyncMock()
        await mgr._handle_report(lab_id, anti_loop_enabled=True, report=_make_report())

    # The fix: _recovering must NOT keep the lab pinned.
    assert lab_id not in mgr._recovering, (
        "_recovering still contains lab_id after resume failure — cluster H regression"
    )


@pytest.mark.asyncio
async def test_recovery_failed_event_broadcast_on_resume_error(db):
    """Resume failure must emit a `lab.loop_recovery_failed` event."""
    from app.database import async_session

    lab_id = uuid.uuid4()
    mgr = LoopManager()
    mgr.configure(async_session)

    fake_runner = AsyncMock()
    fake_runner.pause = AsyncMock()
    fake_runner.resume = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        patch("app.services.lab_runner.get_runner", return_value=fake_runner),
        patch("app.services.loop_detection.manager.ws_manager") as ws_mock,
    ):
        ws_mock.broadcast_to_clients = AsyncMock()
        await mgr._handle_report(lab_id, anti_loop_enabled=True, report=_make_report())

    event_types = [c.args[0].get("type") for c in ws_mock.broadcast_to_clients.call_args_list]
    assert "lab.loop_recovery_failed" in event_types, (
        f"expected lab.loop_recovery_failed in {event_types} — cluster H regression"
    )


@pytest.mark.asyncio
async def test_no_runner_returns_clean(db):
    """When there is no active runner, _recover logs and returns; no crash."""
    from app.database import async_session

    lab_id = uuid.uuid4()
    mgr = LoopManager()
    mgr.configure(async_session)

    with (
        patch("app.services.lab_runner.get_runner", return_value=None),
        patch("app.services.loop_detection.manager.ws_manager") as ws_mock,
    ):
        ws_mock.broadcast_to_clients = AsyncMock()
        # Should not raise.
        await mgr._handle_report(lab_id, anti_loop_enabled=True, report=_make_report())
    assert lab_id not in mgr._recovering
