"""Bob Manager — Resource repository."""

from uuid import UUID

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resource import Resource, ResourceProject
from app.services.authorization import filter_query_by_access, get_default_acl


class ResourceRepository:
    """Data access layer for resources."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, user: dict | None = None) -> list[Resource]:
        """Return all resources the user can see."""
        query = select(Resource).order_by(Resource.name)
        if user:
            query = filter_query_by_access(query, Resource, user)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, resource_id: UUID) -> Resource | None:
        """Return a resource by ID."""
        result = await self.db.execute(select(Resource).where(Resource.id == resource_id))
        return result.scalar_one_or_none()

    async def create(self, resource: Resource) -> Resource:
        """Insert a new resource."""
        self.db.add(resource)
        await self.db.flush()
        await self.db.refresh(resource)
        return resource

    async def update(self, resource_id: UUID, **kwargs) -> Resource | None:
        """Update a resource's fields."""
        await self.db.execute(
            update(Resource).where(Resource.id == resource_id).values(**kwargs)
        )
        await self.db.flush()
        return await self.get_by_id(resource_id)

    async def delete(self, resource_id: UUID) -> bool:
        """Delete a resource."""
        resource = await self.get_by_id(resource_id)
        if resource:
            await self.db.delete(resource)
            await self.db.flush()
            return True
        return False

    # ── Project linkage ──────────────────────────
    async def get_linked_project_ids(self, resource_id: UUID) -> list[UUID]:
        """Return project IDs linked to a resource."""
        result = await self.db.execute(
            select(ResourceProject.project_id).where(
                ResourceProject.resource_id == resource_id
            )
        )
        return [row[0] for row in result.all()]

    async def get_resource_ids_for_project(self, project_id: UUID) -> list[UUID]:
        """Return resource IDs linked to a project."""
        result = await self.db.execute(
            select(ResourceProject.resource_id).where(
                ResourceProject.project_id == project_id
            )
        )
        return [row[0] for row in result.all()]

    async def link_project(self, resource_id: UUID, project_id: UUID) -> bool:
        """Link a project to a resource. Returns False if already linked."""
        result = await self.db.execute(
            select(ResourceProject).where(
                ResourceProject.resource_id == resource_id,
                ResourceProject.project_id == project_id,
            )
        )
        if result.scalar_one_or_none():
            return False
        self.db.add(ResourceProject(resource_id=resource_id, project_id=project_id))
        await self.db.flush()
        return True

    async def unlink_project(self, resource_id: UUID, project_id: UUID) -> bool:
        """Unlink a project from a resource."""
        result = await self.db.execute(
            delete(ResourceProject).where(
                ResourceProject.resource_id == resource_id,
                ResourceProject.project_id == project_id,
            )
        )
        await self.db.flush()
        return result.rowcount > 0
