"""Anti-loop detection — central manager (singleton).

Design highlights:
- Embedding **never** blocks the lab iteration. ``observe_message`` returns
  immediately and schedules a background task.
- Detection runs after the embedding completes; if a red-severity loop is
  found AND the lab has anti-loop enabled, recovery is triggered:
    pause runner → delete looping messages from DB + memory → broadcast
    ``lab.loop_recovered`` → resume runner.
- Yellow / orange severities only emit ``lab.loop_warning``; no action.
- Per-actor in-memory ring buffer keyed by lab_id + actor_key.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Deque
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.services.embedding_service import EmbeddingService
from app.websocket.hub import manager as ws_manager

from .base import LoopReport, MessageRecord, ToolCall
from .detectors import build_default_detector

logger = logging.getLogger(__name__)


# ── Tunables (overridable via env in the future) ─────────────────
WINDOW_SECONDS = 600          # 10 minutes
HISTORY_PER_ACTOR = 12        # ring buffer size per (lab, actor)
RECOVERY_KEEP_TAIL = 0        # how many recent looping msgs to KEEP
MIN_CONTENT_LEN = 20          # don't embed trivially short messages
RED_AUTOACT_SEVERITY = "red"  # severity that triggers auto-recovery
# R14 — hard cap on how long `_recover` can hold the per-lab slot in
# `_recovering`. If the inner async work wedges past this, the wait_for
# fires, the slot is released, and the next loop-warning round gets to
# fire a fresh recovery attempt instead of being permanently no-op'd.
RECOVERY_TIMEOUT_SEC = 60
# Sweeper runs this often. The sweeper is a defence-in-depth net: any
# legitimate recovery completes well inside RECOVERY_TIMEOUT_SEC, so
# the sweeper should only fire on the asyncio.wait_for failure path
# (or a future process-crash-then-restore scenario).
RECOVERY_SWEEP_INTERVAL_SEC = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _ActorBuffer:
    __slots__ = ("messages",)

    def __init__(self):
        self.messages: Deque[MessageRecord] = deque(maxlen=HISTORY_PER_ACTOR)

    def prune_old(self) -> None:
        cutoff = _now() - timedelta(seconds=WINDOW_SECONDS)
        while self.messages and self.messages[0].created_at < cutoff:
            self.messages.popleft()

    def append(self, m: MessageRecord) -> None:
        self.prune_old()
        self.messages.append(m)

    def remove_ids(self, ids: set[UUID]) -> None:
        self.messages = deque(
            (m for m in self.messages if m.message_id not in ids),
            maxlen=HISTORY_PER_ACTOR,
        )

    def clear(self) -> None:
        self.messages.clear()


class LoopManager:
    """Process-wide singleton."""

    def __init__(self):
        # (lab_id, actor_key) → _ActorBuffer
        self._buffers: dict[tuple[UUID, str], _ActorBuffer] = {}
        self._detector = build_default_detector()
        self._recovering: set[UUID] = set()
        # R14 — when we added a lab to `_recovering`. The sweeper uses
        # this to evict entries that overshoot RECOVERY_TIMEOUT_SEC for
        # any reason the wait_for above didn't catch (e.g. an unhandled
        # exception path).
        self._recovery_started_at: dict[UUID, datetime] = {}
        self._session_factory: async_sessionmaker | None = None
        self._lock = asyncio.Lock()

    def configure(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def sweep_stale_recoveries(self) -> int:
        """R14 — drop entries from ``_recovering`` whose recovery has
        been running longer than RECOVERY_TIMEOUT_SEC.

        Defence-in-depth on top of the per-call ``asyncio.wait_for``.
        Returns the count of evicted entries so callers (a periodic
        startup task, an admin probe) can log it.
        """
        cutoff = _now() - timedelta(seconds=RECOVERY_TIMEOUT_SEC)
        async with self._lock:
            stale = [
                lab_id for lab_id, started in self._recovery_started_at.items()
                if started < cutoff
            ]
            for lab_id in stale:
                self._recovering.discard(lab_id)
                self._recovery_started_at.pop(lab_id, None)
                logger.warning(
                    "R14 sweeper — evicting wedged recovery for lab=%s "
                    "(started %s)", lab_id, self._recovery_started_at.get(lab_id),
                )
        return len(stale)

    # ──────────────────────────────────────────────
    # Public entrypoint — called by lab_runner.
    # MUST return immediately; embedding runs in background.
    # ──────────────────────────────────────────────
    def observe_message(
        self,
        *,
        lab_id: UUID,
        anti_loop_enabled: bool,
        message_id: UUID,
        actor_key: str,
        content: str,
        tool_call: ToolCall | None = None,
    ) -> None:
        """Fire-and-forget; schedules background embed + check."""
        # Even if anti-loop is disabled we still keep tool-call history so the
        # operator can see warnings. But we skip embedding to save GPU time.
        record = MessageRecord(
            message_id=message_id,
            actor_key=actor_key,
            content=content or "",
            tool_call=tool_call,
            created_at=_now(),
        )

        # Append synchronously so order is preserved.
        buf = self._buffers.setdefault((lab_id, actor_key), _ActorBuffer())
        buf.append(record)

        # Cheap detector pass (tool-call repeats don't need embeddings).
        try:
            quick_report = self._detector.check(actor_key=actor_key, history=list(buf.messages))
            if quick_report.detected:
                asyncio.create_task(self._handle_report(lab_id, anti_loop_enabled, quick_report))
        except Exception:
            logger.exception("Quick loop check failed for lab=%s actor=%s", lab_id, actor_key)

        # Schedule semantic embedding only if enabled and content is meaningful.
        if anti_loop_enabled and len(record.content.strip()) >= MIN_CONTENT_LEN:
            asyncio.create_task(self._embed_and_check(lab_id, anti_loop_enabled, record))

    # ──────────────────────────────────────────────
    # Background: embed → re-run detector → maybe recover.
    # ──────────────────────────────────────────────
    async def _embed_and_check(
        self,
        lab_id: UUID,
        anti_loop_enabled: bool,
        record: MessageRecord,
    ) -> None:
        try:
            text_for_embed = record.content
            if record.tool_call is not None:
                text_for_embed = f"[tool:{record.tool_call.name}] {text_for_embed}"
            vec = await EmbeddingService.embed_query(text_for_embed[:2000])
            record.embedding = vec
        except Exception as e:
            logger.warning("Loop embedder failed for lab=%s: %s", lab_id, e)
            return

        buf = self._buffers.get((lab_id, record.actor_key))
        if buf is None:
            return

        try:
            report = self._detector.check(
                actor_key=record.actor_key,
                history=list(buf.messages),
            )
        except Exception:
            logger.exception("Loop check failed for lab=%s", lab_id)
            return

        if report.detected:
            await self._handle_report(lab_id, anti_loop_enabled, report)

    # ──────────────────────────────────────────────
    # Severity routing.
    # ──────────────────────────────────────────────
    async def _handle_report(
        self,
        lab_id: UUID,
        anti_loop_enabled: bool,
        report: LoopReport,
    ) -> None:
        payload = {
            "severity": report.severity,
            "score": report.score,
            "signals": [{"name": s.name, "score": s.score, "detail": s.detail} for s in report.signals],
            "loop_message_ids": [str(mid) for mid in report.loop_message_ids],
        }

        # Always emit a warning (so the UI can show banners even when auto-recover is off).
        try:
            await ws_manager.broadcast_to_clients({
                "type": "lab.loop_warning",
                "payload": {"lab_id": str(lab_id), **payload},
            })
        except Exception:
            logger.exception("Failed to broadcast lab.loop_warning")

        if not anti_loop_enabled or report.severity != RED_AUTOACT_SEVERITY:
            return

        async with self._lock:
            if lab_id in self._recovering:
                return
            self._recovering.add(lab_id)
            # R14 — record when recovery started so the periodic sweeper
            # in `_sweep_stale_recoveries` can drop entries whose
            # `_recover` is wedged (a websocket broadcast deadlocking,
            # for example) and would otherwise pin the lab out of all
            # future recovery attempts.
            self._recovery_started_at[lab_id] = _now()

        try:
            # R14 — cap the recovery latency. If the inner await is
            # genuinely stuck we still want the lock released so the
            # next loop-warning round can fire a fresh attempt.
            await asyncio.wait_for(
                self._recover(lab_id, report),
                timeout=RECOVERY_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Loop recovery for lab=%s exceeded %ss; clearing _recovering "
                "so future recoveries can fire (R14)",
                lab_id, RECOVERY_TIMEOUT_SEC,
            )
        finally:
            self._recovering.discard(lab_id)
            self._recovery_started_at.pop(lab_id, None)

    # ──────────────────────────────────────────────
    # Recovery: pause → delete loop msgs → resume.
    # ──────────────────────────────────────────────
    async def _recover(self, lab_id: UUID, report: LoopReport) -> None:
        # Late import avoids circular dependency with lab_runner.
        from app.services.lab_runner import get_runner

        runner = get_runner(lab_id)
        if runner is None:
            logger.info("Loop detected but no active runner for lab=%s", lab_id)
            return

        if self._session_factory is None:
            logger.error("LoopManager not configured with session_factory")
            return

        logger.warning(
            "Anti-loop triggered for lab=%s (score=%d, %d messages)",
            lab_id, report.score, len(report.loop_message_ids),
        )

        # 1) Pause the runner so no new iteration starts during cleanup.
        try:
            await runner.pause()
        except Exception:
            logger.exception("Loop recovery: pause failed for lab=%s", lab_id)
            return

        # 2) Delete looping messages from DB + memory.
        removed = await self._purge_messages(lab_id, report.loop_message_ids)

        # 3) Drop them from our in-memory buffers too so we don't loop on the loop.
        loop_id_set = set(report.loop_message_ids)
        for (lid, _akey), buf in self._buffers.items():
            if lid == lab_id:
                buf.remove_ids(loop_id_set)

        # 4) Persist a loop_event row.
        try:
            await self._record_event(lab_id, report, removed)
        except Exception:
            logger.exception("Loop recovery: failed to record event")

        # 5) Notify UI.
        try:
            await ws_manager.broadcast_to_clients({
                "type": "lab.loop_recovered",
                "payload": {
                    "lab_id": str(lab_id),
                    "severity": report.severity,
                    "score": report.score,
                    "removed_count": removed,
                    "signals": [
                        {"name": s.name, "score": s.score, "detail": s.detail}
                        for s in report.signals
                    ],
                },
            })
        except Exception:
            logger.exception("Failed to broadcast lab.loop_recovered")

        # 6) Resume the lab so it can continue without the looping context.
        try:
            await runner.resume()
        except Exception:
            # Cluster H — the DELETE at step (2) already succeeded, so we
            # cannot "roll back" without re-creating duplicate rows. The
            # lab stays paused; surface a distinct event so the UI can
            # render an actionable banner instead of silently losing the
            # orphan state.
            logger.exception("Loop recovery: resume failed for lab=%s", lab_id)
            try:
                await ws_manager.broadcast_to_clients({
                    "type": "lab.loop_recovery_failed",
                    "payload": {
                        "lab_id": str(lab_id),
                        "severity": report.severity,
                        "score": report.score,
                        "removed_count": removed,
                        "reason": "resume_failed",
                    },
                })
            except Exception:
                logger.exception("Failed to broadcast lab.loop_recovery_failed")

    async def _purge_messages(self, lab_id: UUID, ids: list[UUID]) -> int:
        if not ids:
            return 0
        async with self._session_factory() as db:
            # Cascade via FK ON DELETE handles related rows; lab_memories
            # don't reference messages directly so we leave them intact unless
            # they were summarized from these ids (out of scope).
            res = await db.execute(
                text("DELETE FROM lab_messages WHERE lab_id = :lab_id AND id = ANY(:ids)"),
                {"lab_id": str(lab_id), "ids": [str(i) for i in ids]},
            )
            await db.commit()
            return res.rowcount or 0

    async def _record_event(self, lab_id: UUID, report: LoopReport, removed: int) -> None:
        if self._session_factory is None:
            return
        async with self._session_factory() as db:
            await db.execute(
                text(
                    "INSERT INTO lab_loop_events "
                    "(lab_id, severity, score, signals, removed_message_ids, removed_count, recovered) "
                    "VALUES (:lab_id, :severity, :score, CAST(:signals AS JSONB), "
                    "CAST(:rmids AS JSONB), :removed, true)"
                ),
                {
                    "lab_id": str(lab_id),
                    "severity": report.severity,
                    "score": report.score,
                    "signals": _json_dumps([
                        {"name": s.name, "score": s.score, "detail": s.detail}
                        for s in report.signals
                    ]),
                    "rmids": _json_dumps([str(i) for i in report.loop_message_ids]),
                    "removed": removed,
                },
            )
            await db.commit()

    # ──────────────────────────────────────────────
    # Lab lifecycle hooks.
    # ──────────────────────────────────────────────
    def reset_lab(self, lab_id: UUID) -> None:
        """Drop all in-memory state for a lab (e.g., on stop or reset).

        Cluster H — also discard ``lab_id`` from ``_recovering``. Previously
        a force-stop during recovery left the lab id in the set forever
        (its ``finally`` only ran if the recovery coroutine reached it),
        which silently blocked the next anti-loop trigger on the same lab.
        Discarding here is safe: an in-flight ``_recover`` re-adds itself
        on completion only via its own finally, and the asyncio.Lock keyed
        by ``lab_id`` is not held across this call.
        """
        keys = [k for k in self._buffers if k[0] == lab_id]
        for k in keys:
            self._buffers.pop(k, None)
        self._recovering.discard(lab_id)


# ──────────────────────────────────────────────
# JSON helper kept here so the rest of this file stays import-light.
# ──────────────────────────────────────────────
def _json_dumps(obj) -> str:
    import json
    return json.dumps(obj, default=str)


# ── Singleton accessor ───────────────────────────────────────
_INSTANCE: LoopManager | None = None


def get_loop_manager() -> LoopManager:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = LoopManager()
    return _INSTANCE
