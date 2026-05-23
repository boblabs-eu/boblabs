"""Bob Manager — Server service layer."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server import Server
from app.repositories.server_repo import ServerRepository
from app.schemas.server import ServerCreate, ServerUpdate
from app.websocket.hub import manager


class ServerService:
    """Business logic for server management."""

    def __init__(self, db: AsyncSession) -> None:
        self.repo = ServerRepository(db)

    async def list_servers(self) -> list[Server]:
        """Return all servers with live status overlay."""
        servers = await self.repo.get_all()
        connected = set(manager.get_connected_agents())
        for s in servers:
            if s.name in connected:
                s.status = "online"
        return servers

    async def get_server(self, server_id: UUID) -> Server | None:
        """Return a single server."""
        return await self.repo.get_by_id(server_id)

    async def create_server(self, data: ServerCreate) -> Server:
        """Register a new server manually."""
        server = Server(
            name=data.name,
            host=data.host,
            port=data.port,
        )
        return await self.repo.create(server)

    async def update_server(self, server_id: UUID, data: ServerUpdate) -> Server | None:
        """Update a server's configuration."""
        updates = data.model_dump(exclude_unset=True)
        if not updates:
            return await self.repo.get_by_id(server_id)
        return await self.repo.update(server_id, **updates)

    async def delete_server(self, server_id: UUID) -> bool:
        """Remove a server from the registry."""
        return await self.repo.delete(server_id)

    def get_live_metrics(self, server_name: str) -> dict | None:
        """Return cached real-time metrics from the WebSocket hub."""
        return manager.get_metrics(server_name)

    def get_all_live_metrics(self) -> dict[str, dict]:
        """Return all cached metrics."""
        return manager.get_all_metrics()
