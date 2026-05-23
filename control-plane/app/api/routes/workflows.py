"""Bob Manager — Workflow API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import DbSession
from app.database import async_session
from app.engine.scheduler import WorkflowScheduler
from app.repositories.execution_repo import ExecutionRepository
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
    WorkflowExecuteRequest,
    WorkflowExecutionResponse,
)
from app.services.authorization import require_infra_access
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/workflows", tags=["workflows"], dependencies=[Depends(require_infra_access)])


@router.get("", response_model=list[WorkflowResponse])
async def list_workflows(db: DbSession):
    """Return all workflows."""
    svc = WorkflowService(db)
    return await svc.list_workflows()


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: UUID, db: DbSession):
    """Return a single workflow."""
    svc = WorkflowService(db)
    workflow = await svc.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(data: WorkflowCreate, db: DbSession):
    """Create a new workflow with steps."""
    svc = WorkflowService(db)
    return await svc.create_workflow(data)


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(workflow_id: UUID, data: WorkflowUpdate, db: DbSession):
    """Update a workflow."""
    svc = WorkflowService(db)
    workflow = await svc.update_workflow(workflow_id, data)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: UUID, db: DbSession):
    """Delete a workflow."""
    svc = WorkflowService(db)
    if not await svc.delete_workflow(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")


@router.post("/{workflow_id}/execute", response_model=list[dict])
async def execute_workflow(workflow_id: UUID, data: WorkflowExecuteRequest, db: DbSession):
    """Execute a workflow on one or more servers in parallel."""
    # Verify workflow exists
    svc = WorkflowService(db)
    workflow = await svc.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    scheduler = WorkflowScheduler(async_session)
    results = await scheduler.execute_workflow(workflow_id, data.server_ids)
    return results


@router.get("/{workflow_id}/executions", response_model=list[WorkflowExecutionResponse])
async def get_executions(workflow_id: UUID, db: DbSession):
    """Return execution history for a workflow."""
    repo = ExecutionRepository(db)
    return await repo.get_executions_by_workflow(workflow_id)
