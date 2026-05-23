"""Bob Manager — Task queue service.

PostgreSQL-backed task queue with GPU locking and priority scheduling.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orchestrator import OrchestratorTask
from app.repositories.orchestrator_repo import GpuLockRepository, TaskRepository

logger = logging.getLogger(__name__)


class TaskQueueService:
    """Business logic for task queue and GPU locking."""

    def __init__(self, db: AsyncSession) -> None:
        self.task_repo = TaskRepository(db)
        self.gpu_repo = GpuLockRepository(db)

    async def enqueue(
        self,
        conversation_id: UUID,
        task_type: str = "inference",
        priority: int = 3,
        input_data: dict | None = None,
        agent_id: UUID | None = None,
        parent_task_id: UUID | None = None,
    ) -> OrchestratorTask:
        """Create a new task in the queue."""
        task = OrchestratorTask(
            conversation_id=conversation_id,
            task_type=task_type,
            priority=priority,
            input_data=input_data or {},
            agent_id=agent_id,
            parent_task_id=parent_task_id,
            status="queued",
        )
        return await self.task_repo.create(task)

    async def get_next(self) -> OrchestratorTask | None:
        """Get the next queued task (highest priority, oldest first)."""
        tasks = await self.task_repo.get_queued(limit=1)
        return tasks[0] if tasks else None

    async def start_task(
        self,
        task_id: UUID,
        server_id: UUID | None = None,
        gpu_index: int | None = None,
    ) -> OrchestratorTask | None:
        """Mark a task as running."""
        now = datetime.now(timezone.utc)
        updates: dict = {"status": "running", "started_at": now}
        if server_id:
            updates["server_id"] = server_id
        if gpu_index is not None:
            updates["gpu_index"] = gpu_index
        return await self.task_repo.update(task_id, **updates)

    async def complete_task(
        self,
        task_id: UUID,
        output_data: dict | None = None,
    ) -> OrchestratorTask | None:
        """Mark a task as completed and release GPU lock."""
        now = datetime.now(timezone.utc)
        task = await self.task_repo.update(
            task_id,
            status="completed",
            output_data=output_data,
            completed_at=now,
        )
        await self.gpu_repo.release_by_task(task_id)
        return task

    async def fail_task(
        self, task_id: UUID, error: str
    ) -> OrchestratorTask | None:
        """Mark a task as failed and release GPU lock."""
        now = datetime.now(timezone.utc)
        task = await self.task_repo.update(
            task_id,
            status="failed",
            error=error,
            completed_at=now,
        )
        await self.gpu_repo.release_by_task(task_id)
        return task

    async def acquire_gpu(
        self, server_id: UUID, gpu_index: int, task_id: UUID
    ) -> bool:
        """Try to lock a GPU for a task."""
        return await self.gpu_repo.acquire(server_id, gpu_index, task_id)

    async def release_gpu(self, server_id: UUID, gpu_index: int) -> None:
        """Release a GPU lock."""
        await self.gpu_repo.release(server_id, gpu_index)

    async def get_locked_gpus(self, server_id: UUID) -> list[int]:
        """Get list of locked GPU indices for a server."""
        return await self.gpu_repo.get_locked_gpus(server_id)

    async def get_tasks(
        self, conversation_id: UUID | None = None, limit: int = 50
    ) -> list[OrchestratorTask]:
        """Get recent tasks, optionally filtered by conversation."""
        return await self.task_repo.get_recent(
            limit=limit, conversation_id=conversation_id
        )
