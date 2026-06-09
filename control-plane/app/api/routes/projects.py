"""Bob Manager — Project API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import DbSession, get_current_user
from app.schemas.module import ThemeColorResponse, ThemeColorUpdate
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate, ThemeRenameRequest
from app.services.authorization import Permission, check_permission
from app.services.project_service import ProjectService
from app.services.resource_service import ResourceService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/themes", response_model=list[ThemeColorResponse])
async def list_themes(db: DbSession):
    """Return all unique themes across projects, with colors."""
    svc = ProjectService(db)
    return await svc.get_all_themes()


@router.post("/themes/rename")
async def rename_theme(data: ThemeRenameRequest, db: DbSession):
    """Rename a theme across all projects."""
    svc = ProjectService(db)
    count = await svc.rename_theme(data.old_name, data.new_name)
    return {"old_name": data.old_name, "new_name": data.new_name, "affected_projects": count}


@router.put("/themes/{theme_name}/color", response_model=ThemeColorResponse)
async def update_theme_color(theme_name: str, data: ThemeColorUpdate, db: DbSession):
    """Set or update the color for a theme."""
    svc = ProjectService(db)
    return await svc.set_theme_color(theme_name, data.color)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(db: DbSession, user: dict = Depends(get_current_user)):
    """Return all projects the user can see."""
    svc = ProjectService(db)
    return await svc.list_projects(user=user)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    """Return a single project."""
    svc = ProjectService(db)
    project = await svc.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    check_permission(user, project.acl, Permission.VIEW)
    return project


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    data: ProjectCreate, db: DbSession, user: dict = Depends(get_current_user)
):
    """Create a new project."""
    svc = ProjectService(db)
    return await svc.create_project(data, user=user)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID, data: ProjectUpdate, db: DbSession, user: dict = Depends(get_current_user)
):
    """Update a project."""
    svc = ProjectService(db)
    project = await svc.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    check_permission(user, project.acl, Permission.EDIT)
    updated = await svc.update_project(project_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return updated


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    """Delete a project."""
    svc = ProjectService(db)
    project = await svc.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    check_permission(user, project.acl, Permission.DELETE)
    if not await svc.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/{project_id}/resources")
async def get_project_resources(project_id: UUID, db: DbSession):
    """Return resources linked to this project."""
    svc = ResourceService(db)
    return await svc.get_resources_for_project(project_id)
