"""Bob Manager — Command execution service."""

import asyncio
import uuid
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import CommandHistory
from app.repositories.execution_repo import ExecutionRepository
from app.repositories.server_repo import ServerRepository
from app.websocket.hub import manager

logger = logging.getLogger(__name__)


class CommandService:
    """Business logic for remote command execution."""

    def __init__(self, db: AsyncSession) -> None:
        self.exec_repo = ExecutionRepository(db)
        self.server_repo = ServerRepository(db)

    async def execute_command(
        self, server_id: UUID, command: str, timeout: int = 120
    ) -> dict:
        """Execute a command on a single server.

        Returns the command result with exit code, stdout, stderr.
        """
        server = await self.server_repo.get_by_id(server_id)
        if server is None:
            raise ValueError(f"Server {server_id} not found")

        # Record command in history
        cmd_record = CommandHistory(
            server_id=server_id,
            command=command,
        )
        cmd_record = await self.exec_repo.create_command(cmd_record)

        # Send to agent via WebSocket
        command_id = str(uuid.uuid4())
        future = manager.create_pending(command_id)

        sent = await manager.send_to_agent(server.name, {
            "type": "command.execute",
            "id": command_id,
            "payload": {"command": command},
        })

        if not sent:
            await self.exec_repo.update_command(
                cmd_record.id,
                exit_code=-1,
                stderr="Agent not connected",
                completed_at=datetime.now(timezone.utc),
            )
            return {
                "id": str(cmd_record.id),
                "exit_code": -1,
                "stdout": "",
                "stderr": "Agent not connected",
            }

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            result = {"exit_code": -1, "stdout": "", "stderr": "Command timed out"}

        # Update history
        await self.exec_repo.update_command(
            cmd_record.id,
            exit_code=result.get("exit_code"),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
            completed_at=datetime.now(timezone.utc),
        )

        return {
            "id": str(cmd_record.id),
            **result,
        }

    async def execute_batch(
        self, server_ids: list[UUID], command: str, timeout: int = 120
    ) -> list[dict]:
        """Execute a command on multiple servers in parallel."""

        async def _safe_execute(sid: UUID) -> dict:
            try:
                server = await self.server_repo.get_by_id(sid)
                server_name = server.name if server else str(sid)
                result = await self.execute_command(sid, command, timeout)
                result["server_name"] = server_name
                return result
            except Exception as exc:
                # Look up name if possible
                try:
                    srv = await self.server_repo.get_by_id(sid)
                    name = srv.name if srv else str(sid)
                except Exception:
                    name = str(sid)
                return {
                    "server_name": name,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Error: {exc}",
                }

        tasks = [_safe_execute(sid) for sid in server_ids]
        return await asyncio.gather(*tasks)

    async def get_history(self, server_id: UUID, limit: int = 50) -> list[CommandHistory]:
        """Return command history for a server."""
        return await self.exec_repo.get_command_history(server_id, limit)
