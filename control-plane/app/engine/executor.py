"""Bob Manager — Workflow step executor."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import WorkflowExecution, ExecutionLog
from app.models.workflow import Workflow
from app.repositories.execution_repo import ExecutionRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.websocket.hub import manager

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """Executes workflow steps sequentially on a target server via WebSocket."""

    def __init__(self, db: AsyncSession) -> None:
        self.exec_repo = ExecutionRepository(db)
        self.workflow_repo = WorkflowRepository(db)
        self.db = db

    async def execute_on_server(
        self, workflow_id: UUID, server_id: UUID, server_name: str
    ) -> WorkflowExecution:
        """Execute a workflow on a single server.

        Steps are run sequentially. Each step result is stored.
        """
        workflow = await self.workflow_repo.get_by_id(workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow {workflow_id} not found")

        # Create execution record
        execution = WorkflowExecution(
            workflow_id=workflow_id,
            server_id=server_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        execution = await self.exec_repo.create_execution(execution)
        await self.db.commit()

        # Broadcast start
        await manager.broadcast_to_clients({
            "type": "workflow.execution.start",
            "payload": {
                "execution_id": str(execution.id),
                "workflow": workflow.name,
                "server": server_name,
            },
        })

        final_status = "success"

        for step in sorted(workflow.steps, key=lambda s: s.step_order):
            # Create log entry
            log = ExecutionLog(
                execution_id=execution.id,
                step_id=step.id,
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            log = await self.exec_repo.create_log(log)
            await self.db.commit()

            # Broadcast step start
            await manager.broadcast_to_clients({
                "type": "workflow.step.start",
                "payload": {
                    "execution_id": str(execution.id),
                    "step": step.name,
                    "step_order": step.step_order,
                    "server": server_name,
                },
            })

            # Send command to agent
            command_id = str(uuid.uuid4())
            future = manager.create_pending(command_id)

            sent = await manager.send_to_agent(server_name, {
                "type": "workflow.step.execute",
                "id": command_id,
                "payload": {
                    "command": step.command,
                    "step_name": step.name,
                    "execution_id": str(execution.id),
                },
            })

            if not sent:
                await self.exec_repo.update_log(
                    log.id,
                    status="failed",
                    stderr="Agent not connected",
                    exit_code=-1,
                    completed_at=datetime.now(timezone.utc),
                )
                await self.db.commit()
                final_status = "failed"
                break

            # Wait for result
            try:
                result = await asyncio.wait_for(future, timeout=step.timeout_seconds)
            except asyncio.TimeoutError:
                result = {"exit_code": -1, "stdout": "", "stderr": "Step timed out"}

            step_status = "success" if result.get("exit_code") == 0 else "failed"

            await self.exec_repo.update_log(
                log.id,
                status=step_status,
                exit_code=result.get("exit_code"),
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
                completed_at=datetime.now(timezone.utc),
            )
            await self.db.commit()

            # Broadcast step result
            await manager.broadcast_to_clients({
                "type": "workflow.step.complete",
                "payload": {
                    "execution_id": str(execution.id),
                    "step": step.name,
                    "step_order": step.step_order,
                    "server": server_name,
                    "status": step_status,
                    "exit_code": result.get("exit_code"),
                },
            })

            if step_status == "failed" and not step.continue_on_error:
                final_status = "failed"
                break

        # Finalize execution
        await self.exec_repo.update_execution(
            execution.id,
            status=final_status,
            completed_at=datetime.now(timezone.utc),
        )
        await self.db.commit()

        await manager.broadcast_to_clients({
            "type": "workflow.execution.complete",
            "payload": {
                "execution_id": str(execution.id),
                "workflow": workflow.name,
                "server": server_name,
                "status": final_status,
            },
        })

        return execution
