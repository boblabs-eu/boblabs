"""Bob Manager — RAG repository layer."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag import LabRagAccess, RagCollection, RagDocument
from app.services.authorization import filter_query_by_access, get_default_acl


class RagCollectionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self, user: dict | None = None) -> list[RagCollection]:
        query = select(RagCollection).order_by(RagCollection.display_name)
        if user:
            query = filter_query_by_access(query, RagCollection, user)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, collection_id: UUID) -> RagCollection | None:
        result = await self.db.execute(
            select(RagCollection).where(RagCollection.id == collection_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> RagCollection | None:
        result = await self.db.execute(select(RagCollection).where(RagCollection.name == name))
        return result.scalar_one_or_none()

    async def list_by_app_tag(self, app_id: str) -> list[RagCollection]:
        """List collections whose ``acl.tag`` matches ``app:<app_id>:rag:*``."""
        tag_prefix = f"app:{app_id}:rag:"
        result = await self.db.execute(
            select(RagCollection)
            .where(RagCollection.acl["tag"].astext.startswith(tag_prefix))
            .order_by(RagCollection.display_name)
        )
        return list(result.scalars().all())

    async def create(self, user: dict | None = None, **kwargs) -> RagCollection:
        if user and "acl" not in kwargs:
            kwargs["acl"] = get_default_acl(user.get("sub", "admin"))
        collection = RagCollection(**kwargs)
        self.db.add(collection)
        await self.db.flush()
        await self.db.refresh(collection)
        return collection

    async def update(self, collection_id: UUID, **kwargs) -> RagCollection | None:
        await self.db.execute(
            update(RagCollection).where(RagCollection.id == collection_id).values(**kwargs)
        )
        await self.db.flush()
        return await self.get_by_id(collection_id)

    async def delete(self, collection_id: UUID) -> None:
        await self.db.execute(delete(RagCollection).where(RagCollection.id == collection_id))
        await self.db.flush()


class RagDocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, document_id: UUID) -> RagDocument | None:
        result = await self.db.execute(select(RagDocument).where(RagDocument.id == document_id))
        return result.scalar_one_or_none()

    async def get_by_collection(self, collection_id: UUID) -> list[RagDocument]:
        result = await self.db.execute(
            select(RagDocument)
            .where(RagDocument.collection_id == collection_id)
            .order_by(RagDocument.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(self, **kwargs) -> RagDocument:
        document = RagDocument(**kwargs)
        self.db.add(document)
        await self.db.flush()
        await self.db.refresh(document)
        return document

    async def update(self, document_id: UUID, **kwargs) -> RagDocument | None:
        await self.db.execute(
            update(RagDocument).where(RagDocument.id == document_id).values(**kwargs)
        )
        await self.db.flush()
        return await self.get_by_id(document_id)

    async def delete(self, document_id: UUID) -> None:
        await self.db.execute(delete(RagDocument).where(RagDocument.id == document_id))
        await self.db.flush()

    async def get_collection_stats(self, collection_id: UUID) -> dict:
        result = await self.db.execute(
            select(
                func.count(RagDocument.id),
                func.coalesce(func.sum(RagDocument.chunk_count), 0),
                func.coalesce(func.sum(RagDocument.size_bytes), 0),
            ).where(RagDocument.collection_id == collection_id)
        )
        document_count, chunk_count, total_size_bytes = result.one()
        return {
            "document_count": int(document_count or 0),
            "chunk_count": int(chunk_count or 0),
            "total_size_bytes": int(total_size_bytes or 0),
        }


class LabRagAccessRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_lab(self, lab_id: UUID) -> list[tuple[LabRagAccess, RagCollection]]:
        result = await self.db.execute(
            select(LabRagAccess, RagCollection)
            .join(RagCollection, RagCollection.id == LabRagAccess.collection_id)
            .where(LabRagAccess.lab_id == lab_id)
            .order_by(RagCollection.display_name)
        )
        return list(result.all())

    async def get_entry(self, lab_id: UUID, collection_id: UUID) -> LabRagAccess | None:
        result = await self.db.execute(
            select(LabRagAccess).where(
                LabRagAccess.lab_id == lab_id,
                LabRagAccess.collection_id == collection_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> LabRagAccess:
        entry = LabRagAccess(**kwargs)
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        return entry

    async def update(self, lab_id: UUID, collection_id: UUID, **kwargs) -> LabRagAccess | None:
        await self.db.execute(
            update(LabRagAccess)
            .where(
                LabRagAccess.lab_id == lab_id,
                LabRagAccess.collection_id == collection_id,
            )
            .values(**kwargs)
        )
        await self.db.flush()
        return await self.get_entry(lab_id, collection_id)

    async def delete(self, lab_id: UUID, collection_id: UUID) -> int:
        result = await self.db.execute(
            delete(LabRagAccess).where(
                LabRagAccess.lab_id == lab_id,
                LabRagAccess.collection_id == collection_id,
            )
        )
        await self.db.flush()
        return int(result.rowcount or 0)

    async def has_any_access(self, lab_id: UUID) -> bool:
        result = await self.db.execute(
            select(LabRagAccess.id).where(LabRagAccess.lab_id == lab_id).limit(1)
        )
        return result.first() is not None

    async def has_any_write_access(self, lab_id: UUID) -> bool:
        result = await self.db.execute(
            select(LabRagAccess.id)
            .where(
                LabRagAccess.lab_id == lab_id,
                LabRagAccess.can_write.is_(True),
            )
            .limit(1)
        )
        return result.first() is not None

    async def has_permission(self, lab_id: UUID, collection_id: UUID, permission: str) -> bool:
        column = LabRagAccess.can_write if permission == "write" else LabRagAccess.can_read
        result = await self.db.execute(
            select(LabRagAccess.id).where(
                LabRagAccess.lab_id == lab_id,
                LabRagAccess.collection_id == collection_id,
                column.is_(True),
            )
        )
        return result.first() is not None
