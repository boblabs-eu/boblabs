"""Bob Manager — Server repository."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server import Server
from app.repositories._paginate import MAX_LIMIT, clamp_limit


class ServerRepository:
    """Data access layer for servers."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, limit: int = MAX_LIMIT, offset: int = 0) -> list[Server]:
        """Return all registered servers. P04 — clamped at MAX_LIMIT."""
        result = await self.db.execute(
            select(Server).order_by(Server.name).limit(clamp_limit(limit)).offset(max(0, offset))
        )
        return list(result.scalars().all())

    async def get_by_id(self, server_id: UUID) -> Server | None:
        """Return a server by ID."""
        result = await self.db.execute(select(Server).where(Server.id == server_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Server | None:
        """Return a server by name."""
        result = await self.db.execute(select(Server).where(Server.name == name))
        return result.scalar_one_or_none()

    async def create(self, server: Server) -> Server:
        """Insert a new server."""
        self.db.add(server)
        await self.db.flush()
        await self.db.refresh(server)
        return server

    async def update(self, server_id: UUID, **kwargs) -> Server | None:
        """Update a server's fields."""
        await self.db.execute(update(Server).where(Server.id == server_id).values(**kwargs))
        await self.db.flush()
        return await self.get_by_id(server_id)

    async def delete(self, server_id: UUID) -> bool:
        """Delete a server."""
        server = await self.get_by_id(server_id)
        if server:
            await self.db.delete(server)
            await self.db.flush()
            return True
        return False

    async def get_by_host(self, host: str) -> Server | None:
        """Return a server by host address."""
        result = await self.db.execute(select(Server).where(Server.host == host))
        return result.scalar_one_or_none()
