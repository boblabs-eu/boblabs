"""Bob Manager — Server access API schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ServerCandidateResponse(BaseModel):
    server_id: UUID
    name: str
    host: str
    status: str = "offline"


class LabServerAccessCreate(BaseModel):
    server_ids: list[UUID] = Field(default_factory=list)


class LabServerAccessResponse(BaseModel):
    id: UUID
    lab_id: UUID
    server_id: UUID
    server_name: str
    host: str
    status: str = "offline"
    created_at: datetime | None = None
