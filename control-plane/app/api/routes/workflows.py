"""Bob Manager — Workflow API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import DbSession, get_current_user
from app.database import async_session
from app.engine.scheduler import WorkflowScheduler
from app.repositories.execution_repo import ExecutionRepository
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowExecuteRequest,
    WorkflowExecutionResponse,
    WorkflowResponse,
    WorkflowUpdate,
)
from app.services.authorization import Permission, check_permission, require_infra_access
from app.services.workflow_service import WorkflowService

# Cluster F — keep require_infra_access at the router level (infra-only
# surface) AND add a per-workflow ACL check on every handler that touches
# a specific row. infra_access continues to gate WHO can see workflows
# at all; the ACL gates WHICH workflows each infra user can act on.
router = APIRouter(
    prefix="/workflows", tags=["workflows"], dependencies=[Depends(require_infra_access)]
)


@router.get("", response_model=list[WorkflowResponse])
async def list_workflows(db: DbSession, user: dict = Depends(get_current_user)):
    """Return workflows the caller can view. Admin sees all; non-admin
    infra users see only workflows whose ACL grants them view rights."""
    svc = WorkflowService(db)
    workflows = await svc.list_workflows()
    if user.get("role") == "admin":
        return workflows
    sub = user.get("sub", "")
    visible = []
    for wf in workflows:
        acl = getattr(wf, "acl", None) or {}
        if (
            acl.get("owner") == sub
            or sub in (acl.get("editors") or [])
            or sub in (acl.get("viewers") or [])
        ):
            visible.append(wf)
    return visible


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    """Return a single workflow."""
    svc = WorkflowService(db)
    workflow = await svc.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    check_permission(user, getattr(workflow, "acl", None), Permission.VIEW)
    return workflow


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    data: WorkflowCreate, db: DbSession, user: dict = Depends(get_current_user)
):
    """Create a new workflow with steps. Caller becomes the owner."""
    svc = WorkflowService(db)
    return await svc.create_workflow(data, owner=user.get("sub", "admin"))


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: UUID, data: WorkflowUpdate, db: DbSession, user: dict = Depends(get_current_user)
):
    """Update a workflow. Requires EDIT permission."""
    svc = WorkflowService(db)
    existing = await svc.get_workflow(workflow_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    check_permission(user, getattr(existing, "acl", None), Permission.EDIT)
    workflow = await svc.update_workflow(workflow_id, data)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    """Delete a workflow. Requires DELETE permission (owner-or-admin)."""
    svc = WorkflowService(db)
    existing = await svc.get_workflow(workflow_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    check_permission(user, getattr(existing, "acl", None), Permission.DELETE)
    if not await svc.delete_workflow(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")


@router.post("/{workflow_id}/execute", response_model=list[dict])
async def execute_workflow(
    workflow_id: UUID,
    data: WorkflowExecuteRequest,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    """Execute a workflow on one or more servers in parallel. Requires
    EDIT permission on the workflow (execute is treated as a write)."""
    svc = WorkflowService(db)
    workflow = await svc.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    check_permission(user, getattr(workflow, "acl", None), Permission.EDIT)

    scheduler = WorkflowScheduler(async_session)
    results = await scheduler.execute_workflow(workflow_id, data.server_ids)
    return results


@router.get("/{workflow_id}/executions", response_model=list[WorkflowExecutionResponse])
async def get_executions(workflow_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    """Return execution history for a workflow."""
    svc = WorkflowService(db)
    workflow = await svc.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    check_permission(user, getattr(workflow, "acl", None), Permission.VIEW)
    repo = ExecutionRepository(db)
    return await repo.get_executions_by_workflow(workflow_id)
