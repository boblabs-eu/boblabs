"""Bob Manager — Workflow repository."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.workflow import Workflow, WorkflowStep


class WorkflowRepository:
    """Data access layer for workflows and their steps."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self) -> list[Workflow]:
        """Return all workflows with steps loaded."""
        result = await self.db.execute(
            select(Workflow).options(selectinload(Workflow.steps)).order_by(Workflow.name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, workflow_id: UUID) -> Workflow | None:
        """Return a workflow by ID with steps."""
        result = await self.db.execute(
            select(Workflow)
            .options(selectinload(Workflow.steps))
            .where(Workflow.id == workflow_id)
        )
        return result.scalar_one_or_none()

    async def create(self, workflow: Workflow, steps: list[dict]) -> Workflow:
        """Insert a new workflow with steps."""
        self.db.add(workflow)
        await self.db.flush()

        for i, step_data in enumerate(steps):
            step = WorkflowStep(
                workflow_id=workflow.id,
                step_order=i + 1,
                name=step_data["name"],
                command=step_data["command"],
                timeout_seconds=step_data.get("timeout_seconds", 300),
                continue_on_error=step_data.get("continue_on_error", False),
            )
            self.db.add(step)

        await self.db.flush()
        return await self.get_by_id(workflow.id)  # type: ignore

    async def update(self, workflow_id: UUID, **kwargs) -> Workflow | None:
        """Update workflow fields (not steps)."""
        steps = kwargs.pop("steps", None)
        if kwargs:
            await self.db.execute(
                update(Workflow).where(Workflow.id == workflow_id).values(**kwargs)
            )

        if steps is not None:
            # Delete old steps and recreate
            result = await self.db.execute(
                select(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id)
            )
            for old_step in result.scalars().all():
                await self.db.delete(old_step)
            await self.db.flush()

            for i, step_data in enumerate(steps):
                step = WorkflowStep(
                    workflow_id=workflow_id,
                    step_order=i + 1,
                    name=step_data["name"],
                    command=step_data["command"],
                    timeout_seconds=step_data.get("timeout_seconds", 300),
                    continue_on_error=step_data.get("continue_on_error", False),
                )
                self.db.add(step)

        await self.db.flush()
        return await self.get_by_id(workflow_id)

    async def delete(self, workflow_id: UUID) -> bool:
        """Delete a workflow (steps cascade)."""
        workflow = await self.get_by_id(workflow_id)
        if workflow:
            await self.db.delete(workflow)
            await self.db.flush()
            return True
        return False
