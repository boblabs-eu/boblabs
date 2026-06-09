"""Bob Manager — Execution repository."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.execution import CommandHistory, ExecutionLog, WorkflowExecution


class ExecutionRepository:
    """Data access layer for workflow executions and command history."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Workflow Executions ──────────────────────────

    async def create_execution(self, execution: WorkflowExecution) -> WorkflowExecution:
        """Create a new workflow execution record."""
        self.db.add(execution)
        await self.db.flush()
        await self.db.refresh(execution)
        return execution

    async def get_execution(self, execution_id: UUID) -> WorkflowExecution | None:
        """Return an execution with logs."""
        result = await self.db.execute(
            select(WorkflowExecution)
            .options(selectinload(WorkflowExecution.logs))
            .where(WorkflowExecution.id == execution_id)
        )
        return result.scalar_one_or_none()

    async def get_executions_by_workflow(self, workflow_id: UUID) -> list[WorkflowExecution]:
        """Return all executions for a workflow."""
        result = await self.db.execute(
            select(WorkflowExecution)
            .options(selectinload(WorkflowExecution.logs))
            .where(WorkflowExecution.workflow_id == workflow_id)
            .order_by(WorkflowExecution.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_execution(self, execution_id: UUID, **kwargs) -> None:
        """Update execution status."""
        await self.db.execute(
            update(WorkflowExecution).where(WorkflowExecution.id == execution_id).values(**kwargs)
        )
        await self.db.flush()

    # ── Execution Logs ───────────────────────────────

    async def create_log(self, log: ExecutionLog) -> ExecutionLog:
        """Create a log entry for a step."""
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)
        return log

    async def update_log(self, log_id: UUID, **kwargs) -> None:
        """Update a step log."""
        await self.db.execute(
            update(ExecutionLog).where(ExecutionLog.id == log_id).values(**kwargs)
        )
        await self.db.flush()

    # ── Command History ──────────────────────────────

    async def create_command(self, cmd: CommandHistory) -> CommandHistory:
        """Record a command execution."""
        self.db.add(cmd)
        await self.db.flush()
        await self.db.refresh(cmd)
        return cmd

    async def update_command(self, cmd_id: UUID, **kwargs) -> None:
        """Update a command record."""
        await self.db.execute(
            update(CommandHistory).where(CommandHistory.id == cmd_id).values(**kwargs)
        )
        await self.db.flush()

    async def get_command_history(self, server_id: UUID, limit: int = 50) -> list[CommandHistory]:
        """Return recent commands for a server."""
        result = await self.db.execute(
            select(CommandHistory)
            .where(CommandHistory.server_id == server_id)
            .order_by(CommandHistory.executed_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
