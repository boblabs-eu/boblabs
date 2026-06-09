"""Bob Manager — Lab-Server access repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server import LabServerAccess, Server


class LabServerAccessRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_lab(self, lab_id: UUID) -> list[tuple[LabServerAccess, Server]]:
        result = await self.db.execute(
            select(LabServerAccess, Server)
            .join(Server, Server.id == LabServerAccess.server_id)
            .where(LabServerAccess.lab_id == lab_id)
            .order_by(Server.name.asc())
        )
        return list(result.all())

    async def get_entry(self, lab_id: UUID, server_id: UUID) -> LabServerAccess | None:
        result = await self.db.execute(
            select(LabServerAccess).where(
                LabServerAccess.lab_id == lab_id,
                LabServerAccess.server_id == server_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> LabServerAccess:
        entry = LabServerAccess(**kwargs)
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        return entry

    async def delete(self, lab_id: UUID, server_id: UUID) -> int:
        result = await self.db.execute(
            delete(LabServerAccess).where(
                LabServerAccess.lab_id == lab_id,
                LabServerAccess.server_id == server_id,
            )
        )
        await self.db.flush()
        return int(result.rowcount or 0)

    async def has_any_access(self, lab_id: UUID) -> bool:
        result = await self.db.execute(
            select(LabServerAccess.id).where(LabServerAccess.lab_id == lab_id).limit(1)
        )
        return result.first() is not None

    async def list_server_ids(self, lab_id: UUID) -> list[UUID]:
        result = await self.db.execute(
            select(LabServerAccess.server_id)
            .where(LabServerAccess.lab_id == lab_id)
            .order_by(LabServerAccess.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_server_names(self, lab_id: UUID) -> list[str]:
        """Return names of linked servers (used by tool handler)."""
        result = await self.db.execute(
            select(Server.name)
            .join(LabServerAccess, LabServerAccess.server_id == Server.id)
            .where(LabServerAccess.lab_id == lab_id)
            .order_by(Server.name.asc())
        )
        return list(result.scalars().all())
