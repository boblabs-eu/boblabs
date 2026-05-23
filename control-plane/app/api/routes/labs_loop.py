"""Anti-loop endpoints (history of detected loops + recent in-memory status)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.dependencies import DbSession, get_current_user
from app.services.loop_detection import get_loop_manager

router = APIRouter(tags=["labs"])


@router.get("/{lab_id}/loop-events")
async def list_loop_events(
    lab_id: UUID,
    db: DbSession,
    limit: int = 50,
    user: dict = Depends(get_current_user),
):
    """List historical loop detections for this lab, newest first."""
    res = await db.execute(
        text(
            "SELECT id, severity, score, signals, removed_count, "
            "removed_message_ids, recovered, detected_at "
            "FROM lab_loop_events WHERE lab_id = :lab_id "
            "ORDER BY detected_at DESC LIMIT :limit"
        ),
        {"lab_id": str(lab_id), "limit": max(1, min(limit, 200))},
    )
    rows = res.mappings().all()
    return [dict(r) for r in rows]


@router.get("/{lab_id}/loop-status")
async def get_loop_status(
    lab_id: UUID,
    user: dict = Depends(get_current_user),
):
    """Lightweight in-memory snapshot of recent buffer sizes per actor."""
    mgr = get_loop_manager()
    actors: dict[str, int] = {}
    for (lid, actor_key), buf in mgr._buffers.items():  # noqa: SLF001
        if lid == lab_id:
            actors[actor_key] = len(buf.messages)
    return {"lab_id": str(lab_id), "actors": actors}
