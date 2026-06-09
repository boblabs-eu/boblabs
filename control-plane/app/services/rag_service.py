"""Bob Manager — RAG collections, ingestion, access control, and search."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.rag import RagDocument
from app.repositories.lab_repo import LabRepository
from app.repositories.rag_repo import (
    LabRagAccessRepository,
    RagCollectionRepository,
    RagDocumentRepository,
)
from app.schemas.rag import RagCollectionCreate, RagCollectionUpdate
from app.services.embedding_service import EmbeddingService
from app.services.lightrag_service import LightRagService
from app.services.rag_ingest import choose_splitter, extract_text, split_text

logger = logging.getLogger(__name__)

RAG_STAGING_ROOT = Path(os.environ.get("RAG_STAGING_PATH", settings.rag_staging_path))
_COLLECTION_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_APP_RAG_TAG_PREFIX = "app:"
_APP_RAG_TAG_INFIX = ":rag:"


def make_app_rag_tag(app_id: str, name: str) -> str:
    """Compose the ``acl.tag`` for an app-owned RAG collection."""
    return f"{_APP_RAG_TAG_PREFIX}{app_id}{_APP_RAG_TAG_INFIX}{name}"


def make_app_rag_collection_name(app_id: str, name: str) -> str:
    """Compose the namespaced DB+Qdrant collection name for an app-owned RAG."""
    return f"app__{app_id}__{name}"


def is_app_owned_tag(tag: str | None) -> bool:
    """True if an ``acl.tag`` value identifies an app-owned RAG collection."""
    if not tag:
        return False
    return tag.startswith(_APP_RAG_TAG_PREFIX) and _APP_RAG_TAG_INFIX in tag


def app_id_from_tag(tag: str | None) -> str | None:
    """Extract the app_id from an ``acl.tag`` like ``app:<app_id>:rag:<name>``."""
    if not is_app_owned_tag(tag):
        return None
    # tag = "app:<app_id>:rag:<name>"
    remainder = tag[len(_APP_RAG_TAG_PREFIX) :]
    idx = remainder.find(_APP_RAG_TAG_INFIX)
    if idx <= 0:
        return None
    return remainder[:idx]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _distance(metric: str) -> qdrant.Distance:
    mapping = {
        "cosine": qdrant.Distance.COSINE,
        "euclid": qdrant.Distance.EUCLID,
        "dot": qdrant.Distance.DOT,
    }
    return mapping.get(metric, qdrant.Distance.COSINE)


def _build_metadata_filter(metadata_filter: dict | None) -> qdrant.Filter | None:
    if not metadata_filter:
        return None

    conditions = []
    for key, value in metadata_filter.items():
        conditions.append(
            qdrant.FieldCondition(
                key=f"metadata.{key}",
                match=qdrant.MatchValue(value=value),
            )
        )
    return qdrant.Filter(must=conditions)


async def augment_tool_names_with_rag_access(
    db: AsyncSession, lab_id: UUID, tool_names: list[str] | None
) -> list[str]:
    """Auto-add or strip RAG tools based on access."""

    base = [
        name
        for name in (tool_names or [])
        if name not in {"rag_search", "rag_list_collections", "rag_ingest"}
    ]
    access_repo = LabRagAccessRepository(db)
    has_access = await access_repo.has_any_access(lab_id)
    if has_access:
        base.extend(["rag_list_collections", "rag_search"])
        has_write = await access_repo.has_any_write_access(lab_id)
        if has_write:
            base.append("rag_ingest")
    return list(dict.fromkeys(base))


class RagService:
    """Manages RAG collections, ingestion, search, and permissions."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.collections = RagCollectionRepository(db)
        self.documents = RagDocumentRepository(db)
        self.access = LabRagAccessRepository(db)
        self._qdrant = QdrantClient(url=settings.qdrant_url)

    async def list_collections(self, user: dict | None = None):
        return await self.collections.get_all(user=user)

    async def get_collection(self, collection_id: UUID):
        return await self.collections.get_by_id(collection_id)

    async def create_collection(self, data: RagCollectionCreate, user: dict | None = None):
        if not _COLLECTION_NAME_RE.match(data.name):
            raise ValueError(
                "Collection name may only contain letters, numbers, underscores, and hyphens."
            )

        existing = await self.collections.get_by_name(data.name)
        if existing:
            raise ValueError(f"Collection '{data.name}' already exists.")

        # A05 — create Qdrant FIRST, then the DB row. Pre-fix order:
        # DB flush → Qdrant create. If Qdrant raised (network blip,
        # disk-full), the DB ended up with a row pointing at a
        # non-existent collection and the next ingest call exploded
        # at insert time. New order: ensure Qdrant exists, then persist
        # the row; if the DB raises afterwards, undo the Qdrant
        # collection so the system stays consistent.
        # `data.embedding_dim` is populated by the RagCollectionCreate
        # validator from `data.embedding_model`, so it's safe to read
        # here without an extra catalog lookup.
        await asyncio.to_thread(
            self._ensure_qdrant_collection,
            data.name,
            data.embedding_dim,
            data.distance_metric,
        )
        try:
            collection = await self.collections.create(user=user, **data.model_dump())
        except Exception:
            # Compensation: roll back the Qdrant collection so the next
            # create_collection with the same name doesn't hit the
            # "already exists" guard with no matching DB row.
            try:
                await asyncio.to_thread(self._qdrant.delete_collection, data.name)
            except Exception:
                logger.exception(
                    "A05 — failed to roll back Qdrant collection %r after DB "
                    "create raised; manual cleanup may be required",
                    data.name,
                )
            raise
        return collection

    async def create_app_collection(
        self,
        app_id: str,
        name: str,
        display_name: str | None = None,
        description: str = "",
        embedding_model: str = "all-MiniLM-L6-v2",
        distance_metric: str = "cosine",
    ):
        """Create a consumer-app-owned RAG collection.

        Namespaces the DB+Qdrant name as ``app__<app_id>__<name>`` and stamps
        ``acl.tag = app:<app_id>:rag:<name>``. Idempotent: if a collection with
        the namespaced name already exists AND its tag matches this app, the
        existing row is returned. Cross-app name collisions raise ValueError.
        """
        if not _COLLECTION_NAME_RE.match(name):
            raise ValueError("Name may only contain letters, numbers, underscores, and hyphens.")
        if not _COLLECTION_NAME_RE.match(app_id):
            raise ValueError("app_id may only contain letters, numbers, underscores, and hyphens.")

        full_name = make_app_rag_collection_name(app_id, name)
        tag = make_app_rag_tag(app_id, name)

        existing = await self.collections.get_by_name(full_name)
        if existing:
            existing_tag = (existing.acl or {}).get("tag", "")
            if existing_tag == tag:
                return existing
            raise ValueError(f"Collection name '{full_name}' is taken by another owner.")

        # Resolve embedding dimension via the public schema validator
        data = RagCollectionCreate(
            name=full_name,
            display_name=display_name or name,
            description=description,
            embedding_model=embedding_model,
            distance_metric=distance_metric,
        )
        collection = await self.collections.create(
            acl={
                "owner": f"app:{app_id}",
                "editors": [],
                "viewers": [],
                "tag": tag,
            },
            **data.model_dump(),
        )
        await asyncio.to_thread(
            self._ensure_qdrant_collection,
            collection.name,
            collection.embedding_dim,
            collection.distance_metric,
        )
        return collection

    async def list_app_collections(self, app_id: str):
        """List collections owned by a consumer app (filtered by acl.tag)."""
        return await self.collections.list_by_app_tag(app_id)

    async def get_app_collection_by_name(self, app_id: str, name: str):
        """Look up an app-owned collection by short name (un-namespaced)."""
        full_name = make_app_rag_collection_name(app_id, name)
        collection = await self.collections.get_by_name(full_name)
        if not collection:
            return None
        if (collection.acl or {}).get("tag") != make_app_rag_tag(app_id, name):
            return None
        return collection

    async def assert_owned_by_app(self, collection_name: str, app_id: str):
        """Return the collection if owned by ``app_id``, else raise ValueError."""
        collection = await self.collections.get_by_name(collection_name)
        if not collection:
            raise ValueError(f"Collection '{collection_name}' not found.")
        tag = (collection.acl or {}).get("tag", "")
        expected_prefix = f"{_APP_RAG_TAG_PREFIX}{app_id}{_APP_RAG_TAG_INFIX}"
        if not tag.startswith(expected_prefix):
            raise ValueError(f"Collection '{collection_name}' is not owned by app '{app_id}'.")
        return collection

    async def update_collection(self, collection_id: UUID, data: RagCollectionUpdate):
        collection = await self.collections.get_by_id(collection_id)
        if not collection:
            return None
        updates = data.model_dump(exclude_unset=True)
        if not updates:
            return collection
        updates["updated_at"] = _utcnow()
        return await self.collections.update(collection_id, **updates)

    async def delete_collection(self, collection_id: UUID) -> bool:
        collection = await self.collections.get_by_id(collection_id)
        if not collection:
            return False

        try:
            await asyncio.to_thread(self._qdrant.delete_collection, collection.name)
        except Exception:
            logger.warning(
                "Failed to delete Qdrant collection '%s'", collection.name, exc_info=True
            )

        if collection.rag_mode == "lightrag":
            try:
                await LightRagService.delete_collection(str(collection_id))
            except Exception:
                logger.warning(
                    "Failed to delete LightRAG storage for '%s'", collection.name, exc_info=True
                )

        await self.collections.delete(collection_id)
        staging_dir = RAG_STAGING_ROOT / str(collection_id)
        if staging_dir.exists():
            for item in staging_dir.iterdir():
                try:
                    item.unlink()
                except Exception:
                    logger.warning("Failed to remove staged file %s", item)
            try:
                staging_dir.rmdir()
            except OSError:
                pass
        return True

    async def list_documents(self, collection_id: UUID):
        return await self.documents.get_by_collection(collection_id)

    async def create_document(
        self,
        collection_id: UUID,
        filename: str,
        content_type: str,
        size_bytes: int,
        chunk_size: int,
        chunk_overlap: int,
        splitter: str,
        metadata: dict | None = None,
    ) -> RagDocument:
        return await self.documents.create(
            collection_id=collection_id,
            filename=filename,
            content_type=content_type or "application/octet-stream",
            size_bytes=size_bytes,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            splitter=splitter,
            metadata_json=metadata or {},
        )

    async def ingest_text(
        self,
        collection_id: UUID,
        filename: str,
        content: str,
        content_type: str = "text/plain",
        metadata: dict | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        splitter: str | None = None,
        replace_if_exists: bool = True,
    ) -> RagDocument:
        """Inline-ingest raw text into a collection.

        Combines the upload + reingest flows: stages the content under
        ``RAG_STAGING_ROOT/<collection_id>/`` so future operator-side reingest
        works, then runs the standard pipeline. When ``replace_if_exists`` is
        true (the default), any existing documents with the same ``filename``
        in this collection are deleted first — fixes the linear-storage-bloat
        issue where re-ingesting the same source under the same name keeps
        all old versions.
        """
        collection = await self.collections.get_by_id(collection_id)
        if not collection:
            raise ValueError("Collection not found.")

        if replace_if_exists:
            documents = await self.documents.get_by_collection(collection_id)
            for doc in documents:
                if doc.filename == filename:
                    await self.delete_document(collection_id, doc.id)

        staging_dir = RAG_STAGING_ROOT / str(collection_id)
        staging_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid4().hex}_{filename}"
        staged_path = staging_dir / stored_name
        staged_path.write_text(content, encoding="utf-8")

        cs = chunk_size or collection.default_chunk_size
        co = chunk_overlap if chunk_overlap is not None else collection.default_chunk_overlap
        sp = splitter or collection.default_splitter
        if co > cs:
            raise ValueError("chunk_overlap cannot exceed chunk_size")

        document = await self.create_document(
            collection_id=collection_id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content.encode("utf-8")),
            chunk_size=cs,
            chunk_overlap=co,
            splitter=sp,
            metadata=metadata,
        )
        await self.db.commit()
        return await self.ingest_document(document.id, staged_path)

    async def _resolve_lightrag_model(self, collection):
        """Return model_identifier for a LightRAG collection."""
        from sqlalchemy import select

        from app.models.orchestrator import AIModel

        if not collection.lightrag_model_id:
            raise ValueError("LightRAG collection has no model configured.")
        row = (
            (
                await self.db.execute(
                    select(AIModel).where(AIModel.id == collection.lightrag_model_id)
                )
            )
            .scalars()
            .first()
        )
        if not row:
            raise ValueError("Configured LightRAG model not found.")
        return row.model_identifier

    async def ingest_document(self, document_id: UUID, file_path: Path) -> RagDocument:
        document = await self.documents.get_by_id(document_id)
        if not document:
            raise ValueError("Document not found.")

        collection = await self.collections.get_by_id(document.collection_id)
        if not collection:
            raise ValueError("Collection not found.")

        await self.documents.update(document.id, status="processing", error_message=None)
        await self.db.commit()

        try:
            raw_text = await asyncio.to_thread(extract_text, file_path, document.content_type)

            if collection.rag_mode == "lightrag":
                await self._ingest_lightrag(collection, document, raw_text)
            else:
                await self._ingest_vector(collection, document, raw_text, file_path)

            document = await self.documents.update(
                document.id,
                status="ready",
                chunk_count=document.chunk_count or 0,
                error_message=None,
                ingested_at=_utcnow(),
            )
            await self._refresh_collection_stats(collection.id)
            await self.db.commit()
            return document
        except Exception as exc:
            logger.exception("RAG ingestion failed for document %s", document.id)
            document = await self.documents.update(
                document.id,
                status="failed",
                error_message=str(exc)[:1000],
            )
            await self._refresh_collection_stats(collection.id)
            await self.db.commit()
            return document

    async def _ingest_vector(self, collection, document, raw_text: str, file_path: Path):
        """Standard vector-only ingestion via Qdrant."""
        splitter = choose_splitter(file_path, document.splitter)
        chunks = split_text(
            raw_text,
            splitter=splitter,
            chunk_size=document.chunk_size,
            chunk_overlap=document.chunk_overlap,
        )
        if not chunks:
            raise ValueError("No text chunks were produced from this document.")

        await asyncio.to_thread(
            self._ensure_qdrant_collection,
            collection.name,
            collection.embedding_dim,
            collection.distance_metric,
        )

        vectors = await EmbeddingService.embed_texts(
            chunks,
            model_name=collection.embedding_model,
        )
        points: list[qdrant.PointStruct] = []
        for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
            points.append(
                qdrant.PointStruct(
                    id=str(uuid4()),
                    vector=vector,
                    payload={
                        "document_id": str(document.id),
                        "collection_id": str(collection.id),
                        "text": chunk,
                        "chunk_index": index,
                        "filename": document.filename,
                        "metadata": document.metadata_json or {},
                    },
                )
            )

        for start in range(0, len(points), settings.embedding_batch_size):
            batch = points[start : start + settings.embedding_batch_size]
            await asyncio.to_thread(
                self._qdrant.upsert,
                collection_name=collection.name,
                points=batch,
                wait=True,
            )

        await self.documents.update(
            document.id,
            chunk_count=len(chunks),
            splitter=splitter,
        )

    async def _ingest_lightrag(self, collection, document, raw_text: str):
        """LightRAG ingestion — entity extraction + graph build via LLM."""
        if not raw_text.strip():
            raise ValueError("No text was extracted from this document.")

        model_identifier = await self._resolve_lightrag_model(collection)
        await LightRagService.ingest(
            collection_id=str(collection.id),
            model_name=model_identifier,
            text=raw_text,
            embedding_model=collection.embedding_model,
            embedding_dim=collection.embedding_dim,
        )

    async def delete_document(self, collection_id: UUID, document_id: UUID) -> bool:
        document = await self.documents.get_by_id(document_id)
        if not document or document.collection_id != collection_id:
            return False

        collection = await self.collections.get_by_id(collection_id)
        if collection:
            try:
                await self._delete_document_points(collection.name, document_id)
            except Exception:
                logger.warning(
                    "Failed to delete Qdrant points for document %s", document_id, exc_info=True
                )

        await self.documents.delete(document_id)
        await self._refresh_collection_stats(collection_id)
        await self.db.commit()
        return True

    async def prepare_reingest(
        self,
        collection_id: UUID,
        document_id: UUID,
        *,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        splitter: str | None = None,
    ) -> RagDocument | None:
        document = await self.documents.get_by_id(document_id)
        if not document or document.collection_id != collection_id:
            return None
        collection = await self.collections.get_by_id(collection_id)
        if not collection:
            return None
        if collection:
            try:
                await self._delete_document_points(collection.name, document_id)
            except Exception:
                logger.warning(
                    "Failed to delete Qdrant points for document %s", document_id, exc_info=True
                )

        next_chunk_size = chunk_size if chunk_size is not None else collection.default_chunk_size
        next_chunk_overlap = (
            chunk_overlap if chunk_overlap is not None else collection.default_chunk_overlap
        )
        next_splitter = splitter or collection.default_splitter

        document = await self.documents.update(
            document_id,
            status="pending",
            chunk_size=next_chunk_size,
            chunk_overlap=next_chunk_overlap,
            splitter=next_splitter,
            chunk_count=0,
            error_message=None,
            ingested_at=None,
        )
        await self._refresh_collection_stats(collection_id)
        await self.db.commit()
        return document

    async def check_access(self, lab_id: UUID, collection_name: str, permission: str = "read"):
        collection = await self.collections.get_by_name(collection_name)
        if not collection:
            return None
        allowed = await self.access.has_permission(lab_id, collection.id, permission)
        return collection if allowed else None

    async def list_lab_access(self, lab_id: UUID) -> list[dict]:
        rows = await self.access.get_by_lab(lab_id)
        return [
            {
                "collection_id": collection.id,
                "collection_name": collection.name,
                "collection_display_name": collection.display_name,
                "can_read": access.can_read,
                "can_write": access.can_write,
                "created_at": access.created_at,
            }
            for access, collection in rows
        ]

    async def grant_lab_access(
        self, lab_id: UUID, collection_id: UUID, can_read: bool, can_write: bool
    ) -> dict:
        if not await LabRepository(self.db).get_by_id(lab_id):
            raise ValueError("Lab not found.")
        collection = await self.collections.get_by_id(collection_id)
        if not collection:
            raise ValueError("Collection not found.")

        existing = await self.access.get_entry(lab_id, collection_id)
        if existing:
            raise ValueError("Access entry already exists.")

        entry = await self.access.create(
            lab_id=lab_id,
            collection_id=collection_id,
            can_read=can_read,
            can_write=can_write,
        )
        await self.db.commit()
        return {
            "collection_id": collection.id,
            "collection_name": collection.name,
            "collection_display_name": collection.display_name,
            "can_read": entry.can_read,
            "can_write": entry.can_write,
            "created_at": entry.created_at,
        }

    async def update_lab_access(
        self, lab_id: UUID, collection_id: UUID, can_read: bool | None, can_write: bool | None
    ) -> dict | None:
        collection = await self.collections.get_by_id(collection_id)
        if not collection:
            raise ValueError("Collection not found.")
        updates = {}
        if can_read is not None:
            updates["can_read"] = can_read
        if can_write is not None:
            updates["can_write"] = can_write
        if not updates:
            entry = await self.access.get_entry(lab_id, collection_id)
        else:
            entry = await self.access.update(lab_id, collection_id, **updates)
        if not entry:
            return None
        await self.db.commit()
        return {
            "collection_id": collection.id,
            "collection_name": collection.name,
            "collection_display_name": collection.display_name,
            "can_read": entry.can_read,
            "can_write": entry.can_write,
            "created_at": entry.created_at,
        }

    async def revoke_lab_access(self, lab_id: UUID, collection_id: UUID) -> bool:
        removed = await self.access.delete(lab_id, collection_id)
        await self.db.commit()
        return removed > 0

    async def list_accessible_collections(self, lab_id: UUID) -> list[dict]:
        rows = await self.access.get_by_lab(lab_id)
        visible = []
        for access, collection in rows:
            if not access.can_read:
                continue
            visible.append(
                {
                    "name": collection.name,
                    "display_name": collection.display_name,
                    "description": collection.description,
                    "document_count": collection.document_count,
                    "chunk_count": collection.chunk_count,
                    "rag_mode": collection.rag_mode,
                }
            )
        return visible

    async def search(
        self,
        collection_name: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.3,
        metadata_filter: dict | None = None,
        mode: str | None = None,
    ) -> list[dict]:
        collection = await self.collections.get_by_name(collection_name)
        if not collection:
            raise ValueError(f"Collection '{collection_name}' not found.")

        if collection.rag_mode == "lightrag":
            return await self._search_lightrag(collection, query, mode)

        query_vector = await EmbeddingService.embed_query(
            query,
            model_name=collection.embedding_model,
        )
        query_filter = _build_metadata_filter(metadata_filter)
        hits = await asyncio.to_thread(
            self._search_qdrant,
            collection.name,
            query_vector,
            min(top_k, settings.rag_max_results),
            score_threshold,
            query_filter,
        )
        return [
            {
                "document_id": UUID(str(hit.payload.get("document_id"))),
                "source": str(hit.payload.get("filename", "")),
                "text": str(hit.payload.get("text", "")),
                "score": float(hit.score),
                "chunk": int(hit.payload.get("chunk_index", 0)),
                "metadata": dict(hit.payload.get("metadata", {}) or {}),
            }
            for hit in hits
        ]

    async def _search_lightrag(self, collection, query: str, mode: str | None) -> list[dict]:
        """Delegate search to LightRAG service."""
        search_mode = mode or collection.lightrag_search_mode or "hybrid"
        model_identifier = await self._resolve_lightrag_model(collection)
        result = await LightRagService.search(
            collection_id=str(collection.id),
            model_name=model_identifier,
            query=query,
            mode=search_mode,
            embedding_model=collection.embedding_model,
            embedding_dim=collection.embedding_dim,
        )
        return [
            {
                "document_id": None,
                "source": "lightrag",
                "text": result,
                "score": 1.0,
                "chunk": 0,
                "metadata": {"mode": search_mode},
            }
        ]

    async def search_for_lab(
        self,
        lab_id: UUID,
        collection_name: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.3,
        metadata_filter: dict | None = None,
        mode: str | None = None,
    ) -> list[dict]:
        collection = await self.check_access(lab_id, collection_name, permission="read")
        if not collection:
            raise PermissionError(f"Access denied to collection '{collection_name}'.")

        results = await self.search(
            collection_name=collection.name,
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
            metadata_filter=metadata_filter,
            mode=mode,
        )
        logger.info(
            "RAG query lab=%s collection=%s results=%d query=%s",
            lab_id,
            collection.name,
            len(results),
            query[:500],
        )
        return results

    def _search_qdrant(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int,
        score_threshold: float,
        query_filter: qdrant.Filter | None,
    ):
        query_points = getattr(self._qdrant, "query_points", None)
        if callable(query_points):
            result = query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=limit,
                score_threshold=score_threshold,
                query_filter=query_filter,
            )
            if hasattr(result, "points"):
                return result.points
            return result

        legacy_search = getattr(self._qdrant, "search", None)
        if callable(legacy_search):
            return legacy_search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=limit,
                score_threshold=score_threshold,
                query_filter=query_filter,
            )

        raise RuntimeError("Qdrant client does not support search or query_points.")

    def _ensure_qdrant_collection(self, name: str, dim: int, distance_metric: str) -> None:
        if self._qdrant.collection_exists(name):
            return
        self._qdrant.create_collection(
            collection_name=name,
            vectors_config=qdrant.VectorParams(
                size=dim,
                distance=_distance(distance_metric),
            ),
        )

    async def _refresh_collection_stats(self, collection_id: UUID) -> None:
        stats = await self.documents.get_collection_stats(collection_id)
        stats["updated_at"] = _utcnow()
        await self.collections.update(collection_id, **stats)

    async def _delete_document_points(self, collection_name: str, document_id: UUID) -> None:
        await asyncio.to_thread(
            self._qdrant.delete,
            collection_name=collection_name,
            points_selector=qdrant.FilterSelector(
                filter=qdrant.Filter(
                    must=[
                        qdrant.FieldCondition(
                            key="document_id",
                            match=qdrant.MatchValue(value=str(document_id)),
                        )
                    ]
                )
            ),
            wait=True,
        )


async def run_ingestion_task(document_id: UUID, staged_file_path: str) -> None:
    """Background entry point used by FastAPI BackgroundTasks."""

    async with async_session() as db:
        service = RagService(db)
        await service.ingest_document(document_id, Path(staged_file_path))
