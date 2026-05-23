"""Bob Manager — Tool Sets API routes.

Global reusable tool collections. Mounted at /api/v1/tool-sets.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import DbSession, require_admin
from app.repositories.lab_repo import ToolSetRepository
from app.schemas.orchestrator import (
    ToolSetCreate,
    ToolSetResponse,
    ToolSetUpdate,
)

router = APIRouter(prefix="/tool-sets", tags=["tool-sets"])


@router.get("", response_model=list[ToolSetResponse])
async def list_tool_sets(db: DbSession, _user: dict = Depends(require_admin)):
    return await ToolSetRepository(db).get_all()


@router.post("", response_model=ToolSetResponse, status_code=status.HTTP_201_CREATED)
async def create_tool_set(data: ToolSetCreate, db: DbSession, _user: dict = Depends(require_admin)):
    return await ToolSetRepository(db).create(**data.model_dump(exclude_unset=True))


@router.get("/{ts_id}", response_model=ToolSetResponse)
async def get_tool_set(ts_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    ts = await ToolSetRepository(db).get_by_id(ts_id)
    if not ts:
        raise HTTPException(404, "Tool set not found")
    return ts


@router.patch("/{ts_id}", response_model=ToolSetResponse)
async def update_tool_set(ts_id: UUID, data: ToolSetUpdate, db: DbSession, _user: dict = Depends(require_admin)):
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    ts = await ToolSetRepository(db).update(ts_id, **updates)
    if not ts:
        raise HTTPException(404, "Tool set not found")
    return ts


@router.delete("/{ts_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool_set(ts_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    ts = await ToolSetRepository(db).get_by_id(ts_id)
    if not ts:
        raise HTTPException(404, "Tool set not found")
    await ToolSetRepository(db).delete(ts_id)


@router.post("/{ts_id}/duplicate", response_model=ToolSetResponse, status_code=status.HTTP_201_CREATED)
async def duplicate_tool_set(ts_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    repo = ToolSetRepository(db)
    ts = await repo.get_by_id(ts_id)
    if not ts:
        raise HTTPException(404, "Tool set not found")
    return await repo.create(
        name=f"{ts.name} (copy)",
        description=ts.description,
        tools=list(ts.tools),
    )
