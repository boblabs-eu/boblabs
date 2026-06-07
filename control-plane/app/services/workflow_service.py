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

    async def create_workflow(self, data: WorkflowCreate, owner: str = "admin") -> Workflow:
        """Create a new workflow with steps. ``owner`` becomes
        ``acl.owner`` (cluster F)."""
        steps_list = [s.model_dump() for s in data.steps]
        workflow = Workflow(
            name=data.name,
            description=data.description,
            definition={"steps": steps_list},
            project_id=data.project_id,
            acl={"owner": owner or "admin", "editors": [], "viewers": []},
        )
        return await self.repo.create(workflow, steps_list)

    async def update_workflow(self, workflow_id: UUID, data: WorkflowUpdate) -> Workflow | None:
        """Update a workflow.

        Cluster F — keep ``Workflow.definition`` JSONB and the relational
        ``workflow_steps`` rows in sync. Previously only the relational
        side was rewritten on update, so anything reading ``definition``
        (snapshot endpoints, blueprint export of project-scoped
        workflows) saw stale steps after every edit.
        """
        updates = data.model_dump(exclude_unset=True)
        steps = updates.get("steps")
        if steps is not None:
            updates["steps"] = [
                s if isinstance(s, dict) else s.model_dump() for s in steps
            ]
            # Mirror the canonical step list into the JSONB column in
            # the same transaction.
            updates["definition"] = {"steps": list(updates["steps"])}
        return await self.repo.update(workflow_id, **updates)

    async def delete_workflow(self, workflow_id: UUID) -> bool:
        """Delete a workflow."""
        return await self.repo.delete(workflow_id)
