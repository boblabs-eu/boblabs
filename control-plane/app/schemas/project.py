"""Bob Manager — Project Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ProjectBase(BaseModel):
    """Shared project fields."""

    name: str
    description: str = ""
    github_url: str = ""
    links: list[dict] = []
    themes: list[str] = []
    notes: list[dict] = []
    useful_commands: list[dict] = []


class ProjectCreate(ProjectBase):
    """Schema for creating a project."""

    pass


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""

    name: str | None = None
    description: str | None = None
    github_url: str | None = None
    links: list[dict] | None = None
    themes: list[str] | None = None
    notes: list[dict] | None = None
    useful_commands: list[dict] | None = None


class ThemeRenameRequest(BaseModel):
    """Schema for renaming a theme across all projects."""

    old_name: str
    new_name: str


class ProjectResponse(ProjectBase):
    """Schema returned from API."""

    id: UUID
    acl: dict = {}
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
