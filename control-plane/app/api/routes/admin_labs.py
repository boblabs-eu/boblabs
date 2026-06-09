"""Bob Manager — Admin routes for labs visibility management.

Mirrors the ``admin_consumer_apps`` pattern: a flat read of every lab with
ACL + ``is_public`` flag, plus a single PATCH endpoint to toggle visibility.
The admin override bypasses the per-lab MANAGE permission check that
gates the owner-side PATCH in ``access_tokens.update_acl`` — useful when
an operator needs to flip a lab they don't own (cleanup, take-down,
etc.).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy import update as sa_update

from app.api.dependencies import DbSession, require_admin
from app.models.orchestrator import Lab

router = APIRouter(prefix="/admin/labs", tags=["admin", "labs"])


class LabAdminOut(BaseModel):
    id: str
    name: str
    description: str
    status: str
    is_public: bool
    acl: dict  # {"owner": "...", "editors": [...], "viewers": [...]}
    created_at: str | None = None
    updated_at: str | None = None


class VisibilityIn(BaseModel):
    is_public: bool


@router.get("", response_model=list[LabAdminOut])
async def list_labs(db: DbSession, _admin: dict = Depends(require_admin)):
    """Return every lab with its ACL + visibility flag.

    Sorted by most-recently-updated first so labs the operator is actively
    working on land at the top.
    """
    rows = (await db.execute(select(Lab).order_by(Lab.updated_at.desc()))).scalars().all()
    return [
        LabAdminOut(
            id=str(lab.id),
            name=lab.name,
            description=lab.description or "",
            status=lab.status or "",
            is_public=bool(lab.is_public),
            acl=lab.acl or {"owner": "", "editors": [], "viewers": []},
            created_at=lab.created_at.isoformat() if lab.created_at else None,
            updated_at=lab.updated_at.isoformat() if lab.updated_at else None,
        )
        for lab in rows
    ]


@router.patch("/{lab_id}/visibility")
async def set_lab_visibility(
    lab_id: UUID,
    payload: VisibilityIn,
    db: DbSession,
    _admin: dict = Depends(require_admin),
):
    """Admin override — flip a lab's ``is_public`` flag without owning it."""
    lab = (await db.execute(select(Lab).where(Lab.id == lab_id))).scalar_one_or_none()
    if not lab:
        raise HTTPException(404, "Lab not found")
    await db.execute(
        sa_update(Lab).where(Lab.id == lab_id).values(is_public=bool(payload.is_public))
    )
    await db.flush()
    return {"id": str(lab_id), "is_public": bool(payload.is_public)}
