"""Bob Manager — Workflow Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class WorkflowStepBase(BaseModel):
    """Shared step fields."""
    name: str
    command: str
    timeout_seconds: int = 300
    continue_on_error: bool = False


class WorkflowStepResponse(WorkflowStepBase):
    """Step as returned from API."""
    id: UUID
    step_order: int

    class Config:
        from_attributes = True


class WorkflowBase(BaseModel):
    """Shared workflow fields."""
    name: str
    description: str = ""


class WorkflowCreate(WorkflowBase):
    """Schema for creating a workflow."""
    steps: list[WorkflowStepBase]
    project_id: UUID | None = None


class WorkflowUpdate(BaseModel):
    """Schema for updating a workflow."""
    name: str | None = None
    description: str | None = None
    steps: list[WorkflowStepBase] | None = None
    project_id: UUID | None = None


class WorkflowResponse(WorkflowBase):
    """Workflow as returned from API."""
    id: UUID
    project_id: UUID | None
    steps: list[WorkflowStepResponse]
    # Cluster F — surface ACL so the UI can render share controls.
    acl: dict = {}
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkflowExecuteRequest(BaseModel):
    """Request to execute a workflow."""
    server_ids: list[UUID]


class ExecutionLogResponse(BaseModel):
    """Execution log entry."""
    id: UUID
    step_id: UUID
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    started_at: datetime | None
    completed_at: datetime | None

    class Config:
        from_attributes = True


class WorkflowExecutionResponse(BaseModel):
    """Workflow execution status."""
    id: UUID
    workflow_id: UUID
    server_id: UUID
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    logs: list[ExecutionLogResponse] = []

    class Config:
        from_attributes = True
