"""Bob Manager — Lab server access routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import DbSession, get_current_user
from app.repositories.lab_repo import LabRepository
from app.schemas.server_access import (
    LabServerAccessCreate,
    LabServerAccessResponse,
    ServerCandidateResponse,
)
from app.services.server_access_service import ServerAccessService

router = APIRouter(tags=["labs"])


@router.get("/labs/{lab_id}/server-access", response_model=list[LabServerAccessResponse])
async def list_lab_server_access(lab_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    return await ServerAccessService(db).list_lab_access(lab_id)


@router.get("/labs/{lab_id}/server-access/candidates", response_model=list[ServerCandidateResponse])
async def list_lab_server_candidates(lab_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    return await ServerAccessService(db).list_candidate_servers()


@router.post(
    "/labs/{lab_id}/server-access",
    response_model=list[LabServerAccessResponse],
    status_code=status.HTTP_201_CREATED,
)
async def grant_lab_server_access(
    lab_id: UUID,
    data: LabServerAccessCreate,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    if not data.server_ids:
        raise HTTPException(400, "server_ids is required")

    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")

    try:
        rows = await ServerAccessService(db).grant_lab_access(lab_id, data.server_ids)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    await db.commit()
    return rows


@router.delete("/labs/{lab_id}/server-access/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_lab_server_access(
    lab_id: UUID,
    server_id: UUID,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")

    deleted = await ServerAccessService(db).revoke_lab_access(lab_id, server_id)
    if not deleted:
        raise HTTPException(404, "Access entry not found")
    await db.commit()
