"""Bob Manager — Project ORM model."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Project(Base):
    """Represents a project with metadata and linked workflows."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    github_url: Mapped[str] = mapped_column(String(500), default="")
    links: Mapped[list] = mapped_column(JSONB, default=list)
    themes: Mapped[list] = mapped_column(JSONB, default=list)
    notes: Mapped[list] = mapped_column(JSONB, default=list)
    useful_commands: Mapped[list] = mapped_column(JSONB, default=list)
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
