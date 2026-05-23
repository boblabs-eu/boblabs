"""Bob Manager — Workflow service layer."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import Workflow
from app.repositories.workflow_repo import WorkflowRepository
from app.schemas.workflow import WorkflowCreate, WorkflowUpdate


class WorkflowService:
    """Business logic for workflow CRUD."""

    def __init__(self, db: AsyncSession) -> None:
        self.repo = WorkflowRepository(db)

    async def list_workflows(self) -> list[Workflow]:
        """Return all workflows."""
        return await self.repo.get_all()

    async def get_workflow(self, workflow_id: UUID) -> Workflow | None:
        """Return a single workflow with steps."""
        return await self.repo.get_by_id(workflow_id)

    async def create_workflow(self, data: WorkflowCreate) -> Workflow:
        """Create a new workflow with steps."""
        workflow = Workflow(
            name=data.name,
            description=data.description,
            definition={"steps": [s.model_dump() for s in data.steps]},
            project_id=data.project_id,
        )
        steps = [s.model_dump() for s in data.steps]
        return await self.repo.create(workflow, steps)

    async def update_workflow(self, workflow_id: UUID, data: WorkflowUpdate) -> Workflow | None:
        """Update a workflow."""
        updates = data.model_dump(exclude_unset=True)
        if "steps" in updates and updates["steps"] is not None:
            updates["steps"] = [s if isinstance(s, dict) else s.model_dump() for s in updates["steps"]]
        return await self.repo.update(workflow_id, **updates)

    async def delete_workflow(self, workflow_id: UUID) -> bool:
        """Delete a workflow."""
        return await self.repo.delete(workflow_id)
