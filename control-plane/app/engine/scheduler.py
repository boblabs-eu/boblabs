"""Bob Manager — Workflow parallel scheduler.

Orchestrates workflow execution across multiple servers in parallel.
"""

import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.engine.executor import WorkflowExecutor
from app.repositories.server_repo import ServerRepository

logger = logging.getLogger(__name__)


class WorkflowScheduler:
    """Schedules workflow execution across multiple servers."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.session_factory = session_factory

    async def execute_workflow(self, workflow_id: UUID, server_ids: list[UUID]) -> list[dict]:
        """Execute a workflow on multiple servers in parallel.

        Each server gets its own database session and executor.

        Returns:
            List of execution results per server.
        """
        tasks = []
        for server_id in server_ids:
            tasks.append(self._execute_on_server(workflow_id, server_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                output.append(
                    {
                        "server_id": str(server_ids[i]),
                        "status": "failed",
                        "error": str(result),
                    }
                )
            else:
                output.append(
                    {
                        "server_id": str(result.server_id),
                        "execution_id": str(result.id),
                        "status": result.status,
                    }
                )
        return output

    async def _execute_on_server(self, workflow_id: UUID, server_id: UUID):
        """Execute workflow on a single server with a dedicated session."""
        async with self.session_factory() as db:
            repo = ServerRepository(db)
            server = await repo.get_by_id(server_id)
            if server is None:
                raise ValueError(f"Server {server_id} not found")

            executor = WorkflowExecutor(db)
            return await executor.execute_on_server(workflow_id, server_id, server.name)
