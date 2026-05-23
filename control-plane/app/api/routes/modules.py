"""Bob Manager — Module API routes (modules, steps, tasks).

Auth: every route requires JWT auth and checks the parent project's ACL.
Reads need VIEW; writes need EDIT. Admins bypass via ``check_permission``.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import DbSession, get_current_user
from app.repositories.project_repo import ProjectRepository
from app.schemas.module import (
    ModuleCreate, ModuleUpdate, ModuleResponse, ModuleDetailResponse,
    StepCreate, StepUpdate, StepResponse,
    TaskCreate, TaskUpdate, TaskResponse,
)
from app.services.authorization import check_permission, Permission
from app.services.module_service import ModuleService

router = APIRouter(prefix="/projects/{project_id}/modules", tags=["modules"])


async def _check_project_access(project_id: UUID, user: dict, db, perm: Permission) -> None:
    """Load the project, raise 404 if missing, then enforce ``perm`` on its ACL."""
    project = await ProjectRepository(db).get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    check_permission(user, project.acl, perm)


# ── Modules ──────────────────────────────────────
@router.get("", response_model=list[ModuleDetailResponse])
async def list_modules(project_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    """Return all modules for a project, with their steps and tasks."""
    await _check_project_access(project_id, user, db, Permission.VIEW)
    svc = ModuleService(db)
    modules = await svc.list_modules(project_id)
    out = []
    for mod in modules:
        steps = await svc.list_steps(mod.id)
        tasks = await svc.list_tasks(mod.id)
        d = ModuleDetailResponse.model_validate(mod)
        d.steps = [StepResponse.model_validate(s) for s in steps]
        d.tasks = [TaskResponse.model_validate(t) for t in tasks]
        out.append(d)
    return out


@router.post("", response_model=ModuleResponse, status_code=status.HTTP_201_CREATED)
async def create_module(project_id: UUID, data: ModuleCreate, db: DbSession, user: dict = Depends(get_current_user)):
    await _check_project_access(project_id, user, db, Permission.EDIT)
    svc = ModuleService(db)
    return await svc.create_module(project_id, data)


@router.put("/{module_id}", response_model=ModuleResponse)
async def update_module(project_id: UUID, module_id: UUID, data: ModuleUpdate, db: DbSession, user: dict = Depends(get_current_user)):
    await _check_project_access(project_id, user, db, Permission.EDIT)
    svc = ModuleService(db)
    mod = await svc.update_module(module_id, data)
    if mod is None:
        raise HTTPException(status_code=404, detail="Module not found")
    return mod


@router.delete("/{module_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_module(project_id: UUID, module_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    await _check_project_access(project_id, user, db, Permission.EDIT)
    svc = ModuleService(db)
    if not await svc.delete_module(module_id):
        raise HTTPException(status_code=404, detail="Module not found")


# ── Steps ────────────────────────────────────────
@router.get("/{module_id}/steps", response_model=list[StepResponse])
async def list_steps(project_id: UUID, module_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    await _check_project_access(project_id, user, db, Permission.VIEW)
    svc = ModuleService(db)
    return await svc.list_steps(module_id)


@router.post("/{module_id}/steps", response_model=StepResponse, status_code=status.HTTP_201_CREATED)
async def create_step(project_id: UUID, module_id: UUID, data: StepCreate, db: DbSession, user: dict = Depends(get_current_user)):
    await _check_project_access(project_id, user, db, Permission.EDIT)
    svc = ModuleService(db)
    return await svc.create_step(module_id, data)


@router.put("/{module_id}/steps/{step_id}", response_model=StepResponse)
async def update_step(project_id: UUID, module_id: UUID, step_id: UUID, data: StepUpdate, db: DbSession, user: dict = Depends(get_current_user)):
    await _check_project_access(project_id, user, db, Permission.EDIT)
    svc = ModuleService(db)
    step = await svc.update_step(step_id, data)
    if step is None:
        raise HTTPException(status_code=404, detail="Step not found")
    return step


@router.delete("/{module_id}/steps/{step_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_step(project_id: UUID, module_id: UUID, step_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    await _check_project_access(project_id, user, db, Permission.EDIT)
    svc = ModuleService(db)
    if not await svc.delete_step(step_id):
        raise HTTPException(status_code=404, detail="Step not found")


# ── Tasks ────────────────────────────────────────
@router.get("/{module_id}/tasks", response_model=list[TaskResponse])
async def list_tasks(project_id: UUID, module_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    await _check_project_access(project_id, user, db, Permission.VIEW)
    svc = ModuleService(db)
    return await svc.list_tasks(module_id)


@router.post("/{module_id}/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(project_id: UUID, module_id: UUID, data: TaskCreate, db: DbSession, user: dict = Depends(get_current_user)):
    await _check_project_access(project_id, user, db, Permission.EDIT)
    svc = ModuleService(db)
    return await svc.create_task(module_id, data)


@router.put("/{module_id}/tasks/{task_id}", response_model=TaskResponse)
async def update_task(project_id: UUID, module_id: UUID, task_id: UUID, data: TaskUpdate, db: DbSession, user: dict = Depends(get_current_user)):
    await _check_project_access(project_id, user, db, Permission.EDIT)
    svc = ModuleService(db)
    task = await svc.update_task(task_id, data)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.delete("/{module_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(project_id: UUID, module_id: UUID, task_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    await _check_project_access(project_id, user, db, Permission.EDIT)
    svc = ModuleService(db)
    if not await svc.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
