"""Bob Manager — Web3 API schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TrackedWalletCandidateResponse(BaseModel):
    wallet_id: UUID
    address: str
    label: str = ""
    created_at: datetime | None = None


class LabWeb3AccessCreate(BaseModel):
    wallet_ids: list[UUID] = Field(default_factory=list)


class LabWeb3AccessResponse(BaseModel):
    id: UUID
    lab_id: UUID
    wallet_id: UUID
    address: str
    label: str = ""
    can_read: bool = True
    created_at: datetime | None = None
