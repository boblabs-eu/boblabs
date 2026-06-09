"""Bob Manager — CRON Jobs API routes.

Reusable CRON job library.
Mounted at /api/v1/cron-jobs.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import DbSession, require_admin
from app.repositories.lab_repo import CronJobRepository
from app.schemas.orchestrator import (
    CronJobCreate,
    CronJobResponse,
    CronJobUpdate,
)

router = APIRouter(prefix="/cron-jobs", tags=["cron-jobs"])


@router.get("", response_model=list[CronJobResponse])
async def list_cron_jobs(db: DbSession, _user: dict = Depends(require_admin)):
    return await CronJobRepository(db).get_all()


@router.post("", response_model=CronJobResponse, status_code=status.HTTP_201_CREATED)
async def create_cron_job(data: CronJobCreate, db: DbSession, _user: dict = Depends(require_admin)):
    return await CronJobRepository(db).create(**data.model_dump(exclude_unset=True))


@router.get("/{cj_id}", response_model=CronJobResponse)
async def get_cron_job(cj_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    cj = await CronJobRepository(db).get_by_id(cj_id)
    if not cj:
        raise HTTPException(404, "CRON job not found")
    return cj


@router.patch("/{cj_id}", response_model=CronJobResponse)
async def update_cron_job(
    cj_id: UUID, data: CronJobUpdate, db: DbSession, _user: dict = Depends(require_admin)
):
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    cj = await CronJobRepository(db).update(cj_id, **updates)
    if not cj:
        raise HTTPException(404, "CRON job not found")
    return cj


@router.delete("/{cj_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cron_job(cj_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    cj = await CronJobRepository(db).get_by_id(cj_id)
    if not cj:
        raise HTTPException(404, "CRON job not found")
    await CronJobRepository(db).delete(cj_id)


@router.post(
    "/{cj_id}/duplicate", response_model=CronJobResponse, status_code=status.HTTP_201_CREATED
)
async def duplicate_cron_job(cj_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    repo = CronJobRepository(db)
    cj = await repo.get_by_id(cj_id)
    if not cj:
        raise HTTPException(404, "CRON job not found")
    return await repo.create(
        name=f"{cj.name} (copy)",
        description=cj.description,
        expression=cj.expression,
        method=cj.method,
        instruction=cj.instruction,
    )


@router.get("/{cj_id}/labs")
async def get_cron_job_labs(cj_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    repo = CronJobRepository(db)
    cj = await repo.get_by_id(cj_id)
    if not cj:
        raise HTTPException(404, "CRON job not found")
    return await repo.get_labs_using(cj_id)
