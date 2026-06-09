"""Bob Manager — Resource Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ResourceBase(BaseModel):
    """Shared resource fields."""

    name: str
    description: str = ""
    links: list[dict] = []
    themes: list[str] = []
    notes: list[dict] = []


class ResourceCreate(ResourceBase):
    """Schema for creating a resource."""

    pass


class ResourceUpdate(BaseModel):
    """Schema for updating a resource."""

    name: str | None = None
    description: str | None = None
    links: list[dict] | None = None
    themes: list[str] | None = None
    notes: list[dict] | None = None


class ResourceResponse(ResourceBase):
    """Schema returned from API."""

    id: UUID
    acl: dict = {}
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResourceDetailResponse(ResourceResponse):
    """Resource with linked project summaries."""

    projects: list[dict] = []


class ResourceLinkRequest(BaseModel):
    """Body for linking / unlinking a project to a resource."""

    project_id: UUID
