"""Bob Manager — Blog Post and Blog Token models."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Boolean, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BlogPost(Base):
    """A blog post, created by admin or an authorized agent."""

    __tablename__ = "blog_posts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(String(1000), default="")
    identity: Mapped[str] = mapped_column(String(255), default="admin")
    tags: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BlogToken(Base):
    """Dedicated token for blog posting (used by agents)."""

    __tablename__ = "blog_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(255), default="")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
