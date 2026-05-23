"""Bob Manager — Resource ORM model."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Resource(Base):
    """A resource with themes, links, and notes — linkable to projects."""

    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    links: Mapped[list] = mapped_column(JSONB, default=list)
    themes: Mapped[list] = mapped_column(JSONB, default=list)
    notes: Mapped[list] = mapped_column(JSONB, default=list)
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


class ResourceProject(Base):
    """Many-to-many junction between resources and projects."""

    __tablename__ = "resource_projects"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resources.id", ondelete="CASCADE"),
        primary_key=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
