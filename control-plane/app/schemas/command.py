"""Bob Manager — Command Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CommandRequest(BaseModel):
    """Request to execute a command on a server."""

    command: str


class BatchCommandRequest(BaseModel):
    """Request to execute a command on multiple servers."""

    server_ids: list[UUID]
    command: str


class CommandResponse(BaseModel):
    """Command execution result."""

    id: UUID
    server_id: UUID
    command: str
    exit_code: int | None
    stdout: str
    stderr: str
    executed_at: datetime
    completed_at: datetime | None

    class Config:
        from_attributes = True
