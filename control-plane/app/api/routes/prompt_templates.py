"""Bob Manager — Prompt Templates API routes.

Reusable prompt templates with variable interpolation.
Mounted at /api/v1/prompt-templates.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import DbSession, require_admin
from app.repositories.lab_repo import PromptTemplateRepository
from app.schemas.orchestrator import (
    PromptTemplateCreate,
    PromptTemplateResponse,
    PromptTemplateUpdate,
)

router = APIRouter(prefix="/prompt-templates", tags=["prompt-templates"])


@router.get("", response_model=list[PromptTemplateResponse])
async def list_prompt_templates(db: DbSession, _user: dict = Depends(require_admin)):
    return await PromptTemplateRepository(db).get_all()


@router.post("", response_model=PromptTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt_template(
    data: PromptTemplateCreate, db: DbSession, _user: dict = Depends(require_admin)
):
    return await PromptTemplateRepository(db).create(**data.model_dump(exclude_unset=True))


@router.get("/{pt_id}", response_model=PromptTemplateResponse)
async def get_prompt_template(pt_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    pt = await PromptTemplateRepository(db).get_by_id(pt_id)
    if not pt:
        raise HTTPException(404, "Prompt template not found")
    return pt


@router.patch("/{pt_id}", response_model=PromptTemplateResponse)
async def update_prompt_template(
    pt_id: UUID, data: PromptTemplateUpdate, db: DbSession, _user: dict = Depends(require_admin)
):
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    pt = await PromptTemplateRepository(db).update(pt_id, **updates)
    if not pt:
        raise HTTPException(404, "Prompt template not found")
    return pt


@router.delete("/{pt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt_template(pt_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    pt = await PromptTemplateRepository(db).get_by_id(pt_id)
    if not pt:
        raise HTTPException(404, "Prompt template not found")
    await PromptTemplateRepository(db).delete(pt_id)


@router.post(
    "/{pt_id}/duplicate", response_model=PromptTemplateResponse, status_code=status.HTTP_201_CREATED
)
async def duplicate_prompt_template(
    pt_id: UUID, db: DbSession, _user: dict = Depends(require_admin)
):
    repo = PromptTemplateRepository(db)
    pt = await repo.get_by_id(pt_id)
    if not pt:
        raise HTTPException(404, "Prompt template not found")
    return await repo.create(
        name=f"{pt.name} (copy)",
        description=pt.description,
        content=pt.content,
        target=pt.target,
    )
