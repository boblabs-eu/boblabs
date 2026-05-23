"""Bob Manager — Resource API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import DbSession, get_current_user
from app.schemas.resource import (
    ResourceCreate, ResourceUpdate, ResourceResponse,
    ResourceDetailResponse, ResourceLinkRequest,
)
from app.services.authorization import check_permission, Permission
from app.services.resource_service import ResourceService

router = APIRouter(prefix="/resources", tags=["resources"])


@router.get("", response_model=list[ResourceResponse])
async def list_resources(db: DbSession, user: dict = Depends(get_current_user)):
    """Return all resources the user can see."""
    svc = ResourceService(db)
    return await svc.list_resources(user=user)


@router.get("/{resource_id}", response_model=ResourceDetailResponse)
async def get_resource(resource_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    """Return a single resource with linked projects."""
    svc = ResourceService(db)
    resource = await svc.get_resource(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    check_permission(user, resource.acl, Permission.VIEW)
    projects = await svc.get_linked_projects(resource_id)
    resp = ResourceDetailResponse.model_validate(resource)
    resp.projects = projects
    return resp


@router.post("", response_model=ResourceResponse, status_code=status.HTTP_201_CREATED)
async def create_resource(data: ResourceCreate, db: DbSession, user: dict = Depends(get_current_user)):
    """Create a new resource."""
    svc = ResourceService(db)
    return await svc.create_resource(data, user=user)


@router.put("/{resource_id}", response_model=ResourceResponse)
async def update_resource(resource_id: UUID, data: ResourceUpdate, db: DbSession, user: dict = Depends(get_current_user)):
    """Update a resource."""
    svc = ResourceService(db)
    resource = await svc.get_resource(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    check_permission(user, resource.acl, Permission.EDIT)
    updated = await svc.update_resource(resource_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return updated


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(resource_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    """Delete a resource."""
    svc = ResourceService(db)
    resource = await svc.get_resource(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    check_permission(user, resource.acl, Permission.DELETE)
    if not await svc.delete_resource(resource_id):
        raise HTTPException(status_code=404, detail="Resource not found")


# ── Project linkage ──────────────────────────────
@router.get("/{resource_id}/projects")
async def get_linked_projects(resource_id: UUID, db: DbSession):
    """Return projects linked to this resource."""
    svc = ResourceService(db)
    return await svc.get_linked_projects(resource_id)


@router.post("/{resource_id}/projects", status_code=status.HTTP_201_CREATED)
async def link_project(resource_id: UUID, data: ResourceLinkRequest, db: DbSession):
    """Link a project to a resource."""
    svc = ResourceService(db)
    linked = await svc.link_project(resource_id, data.project_id)
    if not linked:
        raise HTTPException(status_code=409, detail="Already linked")
    return {"status": "linked"}


@router.delete("/{resource_id}/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_project(resource_id: UUID, project_id: UUID, db: DbSession):
    """Unlink a project from a resource."""
    svc = ResourceService(db)
    if not await svc.unlink_project(resource_id, project_id):
        raise HTTPException(status_code=404, detail="Link not found")
