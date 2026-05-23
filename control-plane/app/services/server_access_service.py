"""Bob Manager — Lab-scoped server access service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.server_access_repo import LabServerAccessRepository
from app.repositories.server_repo import ServerRepository


async def augment_tool_names_with_server_access(
    db: AsyncSession, lab_id: UUID, tool_names: list[str] | None
) -> list[str]:
    """Strip control_server unless lab has linked servers AND it was explicitly selected."""
    original = tool_names or []
    has_explicit = "control_server" in original
    base = [name for name in original if name != "control_server"]

    if has_explicit:
        access_repo = LabServerAccessRepository(db)
        if await access_repo.has_any_access(lab_id):
            base.append("control_server")

    return list(dict.fromkeys(base))


class ServerAccessService:
    """Service for lab-scoped server access management."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.access = LabServerAccessRepository(db)

    async def list_lab_access(self, lab_id: UUID) -> list[dict]:
        rows = await self.access.get_by_lab(lab_id)
        return [
            {
                "id": str(entry.id),
                "lab_id": str(entry.lab_id),
                "server_id": str(server.id),
                "server_name": server.name,
                "host": server.host,
                "status": server.status,
                "created_at": entry.created_at,
            }
            for entry, server in rows
        ]

    async def list_candidate_servers(self) -> list[dict]:
        repo = ServerRepository(self.db)
        servers = await repo.get_all()
        return [
            {
                "server_id": str(s.id),
                "name": s.name,
                "host": s.host,
                "status": s.status,
            }
            for s in servers
        ]

    async def grant_lab_access(self, lab_id: UUID, server_ids: list[UUID]) -> list[dict]:
        granted: list[dict] = []
        server_repo = ServerRepository(self.db)
        for server_id in dict.fromkeys(server_ids):
            server = await server_repo.get_by_id(server_id)
            if server is None:
                raise ValueError(f"Server {server_id} not found")

            entry = await self.access.get_entry(lab_id, server.id)
            if entry is None:
                entry = await self.access.create(
                    lab_id=lab_id,
                    server_id=server.id,
                )

            granted.append(
                {
                    "id": str(entry.id),
                    "lab_id": str(entry.lab_id),
                    "server_id": str(server.id),
                    "server_name": server.name,
                    "host": server.host,
                    "status": server.status,
                    "created_at": entry.created_at,
                }
            )
        return granted

    async def revoke_lab_access(self, lab_id: UUID, server_id: UUID) -> bool:
        deleted = await self.access.delete(lab_id, server_id)
        return deleted > 0
