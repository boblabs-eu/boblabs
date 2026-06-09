"""Bob Manager — Consumer App repository."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consumer_app import ConsumerApp
from app.repositories._paginate import MAX_LIMIT, clamp_limit


class ConsumerAppRepository:
    """Data access layer for consumer apps (HMAC-authenticated private apps)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, limit: int = MAX_LIMIT, offset: int = 0) -> list[ConsumerApp]:
        # P04 — cap unbounded scan. Admin UI usually shows <10 apps.
        result = await self.db.execute(
            select(ConsumerApp)
            .order_by(ConsumerApp.created_at.desc())
            .limit(clamp_limit(limit))
            .offset(max(0, offset))
        )
        return list(result.scalars().all())

    async def get_by_id(self, app_uuid: UUID) -> ConsumerApp | None:
        result = await self.db.execute(select(ConsumerApp).where(ConsumerApp.id == app_uuid))
        return result.scalar_one_or_none()

    async def get_by_app_id(self, app_id: str) -> ConsumerApp | None:
        result = await self.db.execute(select(ConsumerApp).where(ConsumerApp.app_id == app_id))
        return result.scalar_one_or_none()

    async def create(self, app_id: str, name: str, secret: str, notes: str = "") -> ConsumerApp:
        app = ConsumerApp(
            app_id=app_id,
            name=name,
            secret=secret,
            notes=notes,
        )
        self.db.add(app)
        await self.db.flush()
        await self.db.refresh(app)
        return app

    async def delete(self, app_uuid: UUID) -> bool:
        """Hard-delete a consumer app row. Returns True if a row was removed."""
        result = await self.db.execute(
            delete(ConsumerApp).where(ConsumerApp.id == app_uuid).returning(ConsumerApp.id)
        )
        await self.db.flush()
        return result.scalar_one_or_none() is not None

    async def revoke(self, app_uuid: UUID) -> bool:
        result = await self.db.execute(
            update(ConsumerApp)
            .where(ConsumerApp.id == app_uuid, ConsumerApp.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
            .returning(ConsumerApp.id)
        )
        await self.db.flush()
        return result.scalar_one_or_none() is not None

    async def touch_last_used(self, app_uuid: UUID) -> None:
        """Best-effort update of last_used_at; failures are silently ignored."""
        await self.db.execute(
            update(ConsumerApp)
            .where(ConsumerApp.id == app_uuid)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        await self.db.flush()
