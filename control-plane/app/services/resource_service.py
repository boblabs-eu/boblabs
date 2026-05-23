"""Bob Manager — Resource service layer."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resource import Resource
from app.models.project import Project
from app.repositories.resource_repo import ResourceRepository
from app.schemas.resource import ResourceCreate, ResourceUpdate
from app.services.authorization import get_default_acl


class ResourceService:
    """Business logic for resource management."""

    def __init__(self, db: AsyncSession) -> None:
        self.repo = ResourceRepository(db)
        self.db = db

    async def list_resources(self, user: dict | None = None) -> list[Resource]:
        return await self.repo.get_all(user=user)

    async def get_resource(self, resource_id: UUID) -> Resource | None:
        return await self.repo.get_by_id(resource_id)

    async def create_resource(self, data: ResourceCreate, user: dict | None = None) -> Resource:
        acl = get_default_acl(user.get("sub", "admin")) if user else get_default_acl("admin")
        resource = Resource(
            name=data.name,
            description=data.description,
            links=data.links,
            themes=data.themes,
            notes=data.notes,
            acl=acl,
        )
        return await self.repo.create(resource)

    async def update_resource(self, resource_id: UUID, data: ResourceUpdate) -> Resource | None:
        updates = data.model_dump(exclude_unset=True)
        if not updates:
            return await self.repo.get_by_id(resource_id)
        return await self.repo.update(resource_id, **updates)

    async def delete_resource(self, resource_id: UUID) -> bool:
        return await self.repo.delete(resource_id)

    # ── Linked projects ──────────────────────────
    async def get_linked_projects(self, resource_id: UUID) -> list[dict]:
        """Return summary dicts of projects linked to a resource."""
        project_ids = await self.repo.get_linked_project_ids(resource_id)
        if not project_ids:
            return []
        result = await self.db.execute(
            select(Project).where(Project.id.in_(project_ids))
        )
        return [
            {"id": str(p.id), "name": p.name, "themes": p.themes or []}
            for p in result.scalars().all()
        ]

    async def get_resources_for_project(self, project_id: UUID) -> list[dict]:
        """Return summary dicts of resources linked to a project."""
        resource_ids = await self.repo.get_resource_ids_for_project(project_id)
        if not resource_ids:
            return []
        result = await self.db.execute(
            select(Resource).where(Resource.id.in_(resource_ids))
        )
        return [
            {"id": str(r.id), "name": r.name, "themes": r.themes or []}
            for r in result.scalars().all()
        ]

    async def link_project(self, resource_id: UUID, project_id: UUID) -> bool:
        return await self.repo.link_project(resource_id, project_id)

    async def unlink_project(self, resource_id: UUID, project_id: UUID) -> bool:
        return await self.repo.unlink_project(resource_id, project_id)
