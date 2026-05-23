"""Bob Manager — Project repository."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.services.authorization import filter_query_by_access, get_default_acl


class ProjectRepository:
    """Data access layer for projects."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, user: dict | None = None) -> list[Project]:
        """Return all projects the user can see."""
        query = select(Project).order_by(Project.name)
        if user:
            query = filter_query_by_access(query, Project, user)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, project_id: UUID) -> Project | None:
        """Return a project by ID."""
        result = await self.db.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    async def create(self, project: Project) -> Project:
        """Insert a new project."""
        self.db.add(project)
        await self.db.flush()
        await self.db.refresh(project)
        return project

    async def update(self, project_id: UUID, **kwargs) -> Project | None:
        """Update a project's fields."""
        await self.db.execute(
            update(Project).where(Project.id == project_id).values(**kwargs)
        )
        await self.db.flush()
        return await self.get_by_id(project_id)

    async def delete(self, project_id: UUID) -> bool:
        """Delete a project."""
        project = await self.get_by_id(project_id)
        if project:
            await self.db.delete(project)
            await self.db.flush()
            return True
        return False
