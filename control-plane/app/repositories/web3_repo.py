"""Bob Manager — Web3 repository layer."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wallet import LabWeb3Access, Wallet


class LabWeb3AccessRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_lab(self, lab_id: UUID) -> list[tuple[LabWeb3Access, Wallet]]:
        result = await self.db.execute(
            select(LabWeb3Access, Wallet)
            .join(Wallet, Wallet.id == LabWeb3Access.wallet_id)
            .where(
                LabWeb3Access.lab_id == lab_id,
                LabWeb3Access.can_read.is_(True),
            )
            .order_by(Wallet.label.asc(), Wallet.address.asc())
        )
        return list(result.all())

    async def get_entry(self, lab_id: UUID, wallet_id: UUID) -> LabWeb3Access | None:
        result = await self.db.execute(
            select(LabWeb3Access).where(
                LabWeb3Access.lab_id == lab_id,
                LabWeb3Access.wallet_id == wallet_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> LabWeb3Access:
        entry = LabWeb3Access(**kwargs)
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        return entry

    async def update(self, lab_id: UUID, wallet_id: UUID, **kwargs) -> LabWeb3Access | None:
        await self.db.execute(
            update(LabWeb3Access)
            .where(
                LabWeb3Access.lab_id == lab_id,
                LabWeb3Access.wallet_id == wallet_id,
            )
            .values(**kwargs)
        )
        await self.db.flush()
        return await self.get_entry(lab_id, wallet_id)

    async def delete(self, lab_id: UUID, wallet_id: UUID) -> int:
        result = await self.db.execute(
            delete(LabWeb3Access).where(
                LabWeb3Access.lab_id == lab_id,
                LabWeb3Access.wallet_id == wallet_id,
            )
        )
        await self.db.flush()
        return int(result.rowcount or 0)

    async def has_any_access(self, lab_id: UUID) -> bool:
        result = await self.db.execute(
            select(LabWeb3Access.id)
            .where(
                LabWeb3Access.lab_id == lab_id,
                LabWeb3Access.can_read.is_(True),
            )
            .limit(1)
        )
        return result.first() is not None

    async def list_wallet_ids(self, lab_id: UUID) -> list[UUID]:
        result = await self.db.execute(
            select(LabWeb3Access.wallet_id)
            .where(
                LabWeb3Access.lab_id == lab_id,
                LabWeb3Access.can_read.is_(True),
            )
            .order_by(LabWeb3Access.created_at.asc())
        )
        return list(result.scalars().all())
