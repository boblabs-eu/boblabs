"""Bob Manager — Server API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import DbSession
from app.schemas.server import ServerCreate, ServerUpdate, ServerResponse
from app.services.server_service import ServerService
from app.services.metrics_service import MetricsService
from app.services.authorization import require_infra_access

router = APIRouter(prefix="/servers", tags=["servers"], dependencies=[Depends(require_infra_access)])


@router.get("", response_model=list[ServerResponse])
async def list_servers(db: DbSession) -> list:
    """Return all registered servers."""
    svc = ServerService(db)
    return await svc.list_servers()


@router.get("/{server_id}", response_model=ServerResponse)
async def get_server(server_id: UUID, db: DbSession):
    """Return a single server by ID."""
    svc = ServerService(db)
    server = await svc.get_server(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


@router.post("", response_model=ServerResponse, status_code=status.HTTP_201_CREATED)
async def create_server(data: ServerCreate, db: DbSession):
    """Manually register a new server."""
    svc = ServerService(db)
    return await svc.create_server(data)


@router.put("/{server_id}", response_model=ServerResponse)
async def update_server(server_id: UUID, data: ServerUpdate, db: DbSession):
    """Update a server's configuration."""
    svc = ServerService(db)
    server = await svc.update_server(server_id, data)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(server_id: UUID, db: DbSession):
    """Remove a server from the registry."""
    svc = ServerService(db)
    if not await svc.delete_server(server_id):
        raise HTTPException(status_code=404, detail="Server not found")


@router.get("/{server_id}/metrics")
async def get_server_metrics(server_id: UUID, db: DbSession):
    """Return live cached metrics for a server."""
    svc = ServerService(db)
    server = await svc.get_server(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    metrics_svc = MetricsService()
    metrics = metrics_svc.get_server_metrics(server.name)
    if metrics is None:
        raise HTTPException(status_code=404, detail="No metrics available")
    return metrics


@router.get("/{server_id}/processes")
async def get_processes(server_id: UUID, db: DbSession):
    """Request process list from agent."""
    svc = ServerService(db)
    server = await svc.get_server(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    metrics_svc = MetricsService()
    result = await metrics_svc.request_inspection(server.name, "processes")
    if result is None:
        raise HTTPException(status_code=503, detail="Agent unavailable")
    return result


@router.get("/{server_id}/services")
async def get_services(server_id: UUID, db: DbSession):
    """Request systemctl services from agent."""
    svc = ServerService(db)
    server = await svc.get_server(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    metrics_svc = MetricsService()
    result = await metrics_svc.request_inspection(server.name, "services")
    if result is None:
        raise HTTPException(status_code=503, detail="Agent unavailable")
    return result


@router.get("/{server_id}/crontabs")
async def get_crontabs(server_id: UUID, db: DbSession):
    """Request crontab entries from agent."""
    svc = ServerService(db)
    server = await svc.get_server(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    metrics_svc = MetricsService()
    result = await metrics_svc.request_inspection(server.name, "crontabs")
    if result is None:
        raise HTTPException(status_code=503, detail="Agent unavailable")
    return result


@router.get("/{server_id}/ports")
async def get_ports(server_id: UUID, db: DbSession):
    """Request open ports from agent."""
    svc = ServerService(db)
    server = await svc.get_server(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    metrics_svc = MetricsService()
    result = await metrics_svc.request_inspection(server.name, "ports")
    if result is None:
        raise HTTPException(status_code=503, detail="Agent unavailable")
    return result


@router.get("/{server_id}/firewall")
async def get_firewall(server_id: UUID, db: DbSession):
    """Request UFW firewall status from agent."""
    svc = ServerService(db)
    server = await svc.get_server(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    metrics_svc = MetricsService()
    result = await metrics_svc.request_inspection(server.name, "firewall")
    if result is None:
        raise HTTPException(status_code=503, detail="Agent unavailable")
    return result
