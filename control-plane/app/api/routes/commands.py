"""Bob Manager — Command API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import DbSession
from app.schemas.command import BatchCommandRequest, CommandRequest, CommandResponse
from app.services.authorization import require_infra_access
from app.services.command_service import CommandService

router = APIRouter(
    prefix="/commands", tags=["commands"], dependencies=[Depends(require_infra_access)]
)


@router.post("/servers/{server_id}", response_model=dict)
async def execute_command(server_id: UUID, data: CommandRequest, db: DbSession):
    """Execute a command on a single server."""
    svc = CommandService(db)
    try:
        result = await svc.execute_command(server_id, data.command)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/batch", response_model=list)
async def execute_batch_command(data: BatchCommandRequest, db: DbSession):
    """Execute a command on multiple servers in parallel."""
    svc = CommandService(db)
    results = await svc.execute_batch(data.server_ids, data.command)
    return results


@router.get("/servers/{server_id}/history", response_model=list[CommandResponse])
async def get_command_history(server_id: UUID, db: DbSession, limit: int = 50):
    """Return command execution history for a server."""
    svc = CommandService(db)
    return await svc.get_history(server_id, limit)
