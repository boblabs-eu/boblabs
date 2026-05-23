"""Bob Manager — RAG ORM models."""

import uuid
from datetime import datetime

from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RagCollection(Base):
    """Metadata and defaults for a semantic-search collection."""

    __tablename__ = "rag_collections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")

    embedding_model: Mapped[str] = mapped_column(
        String(255), default="all-MiniLM-L6-v2"
    )
    embedding_dim: Mapped[int] = mapped_column(Integer, default=384)
    distance_metric: Mapped[str] = mapped_column(String(20), default="cosine")

    default_chunk_size: Mapped[int] = mapped_column(Integer, default=512)
    default_chunk_overlap: Mapped[int] = mapped_column(Integer, default=64)
    default_splitter: Mapped[str] = mapped_column(String(50), default="recursive")

    document_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    total_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

    # LightRAG fields
    rag_mode: Mapped[str] = mapped_column(String(20), default="vector", server_default="vector")
    lightrag_model_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_models.id", ondelete="SET NULL"), nullable=True
    )
    lightrag_search_mode: Mapped[str] = mapped_column(String(10), default="hybrid", server_default="hybrid")

    acl: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        server_default='{"owner":"admin","editors":[],"viewers":[]}',
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RagDocument(Base):
    """Tracks a source document ingested into a collection."""

    __tablename__ = "rag_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rag_collections.id", ondelete="CASCADE"),
        nullable=False,
    )

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), default="text/plain")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False)
    splitter: Mapped[str] = mapped_column(String(50), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    ingested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LabRagAccess(Base):
    """Per-lab collection permissions."""

    __tablename__ = "lab_rag_access"
    __table_args__ = (
        UniqueConstraint("lab_id", "collection_id", name="uq_lab_rag_access"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lab_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("labs.id", ondelete="CASCADE"),
        nullable=False,
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rag_collections.id", ondelete="CASCADE"),
        nullable=False,
    )
    can_read: Mapped[bool] = mapped_column(Boolean, default=True)
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
