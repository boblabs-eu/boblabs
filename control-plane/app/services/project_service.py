"""Bob Manager — Project service layer."""

from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.resource import Resource
from app.models.theme_color import ThemeColor
from app.repositories.project_repo import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services.authorization import get_default_acl

# Default palette for auto-assigning colors to new themes
_DEFAULT_PALETTE = [
    "#a855f7", "#3b82f6", "#ef4444", "#22c55e", "#f59e0b",
    "#ec4899", "#06b6d4", "#f97316", "#8b5cf6", "#14b8a6",
    "#e11d48", "#84cc16", "#6366f1", "#0ea5e9", "#d946ef",
]


class ProjectService:
    """Business logic for project management."""

    def __init__(self, db: AsyncSession) -> None:
        self.repo = ProjectRepository(db)
        self.db = db

    async def list_projects(self, user: dict | None = None) -> list[Project]:
        """Return all projects the user can see."""
        return await self.repo.get_all(user=user)

    async def get_project(self, project_id: UUID) -> Project | None:
        """Return a single project."""
        return await self.repo.get_by_id(project_id)

    async def create_project(self, data: ProjectCreate, user: dict | None = None) -> Project:
        """Create a new project."""
        acl = get_default_acl(user.get("sub", "admin")) if user else get_default_acl("admin")
        project = Project(
            name=data.name,
            description=data.description,
            github_url=data.github_url,
            links=data.links,
            themes=data.themes,
            notes=data.notes,
            useful_commands=data.useful_commands,
            acl=acl,
        )
        return await self.repo.create(project)

    async def update_project(self, project_id: UUID, data: ProjectUpdate) -> Project | None:
        """Update a project."""
        updates = data.model_dump(exclude_unset=True)
        if not updates:
            return await self.repo.get_by_id(project_id)
        return await self.repo.update(project_id, **updates)

    async def delete_project(self, project_id: UUID) -> bool:
        """Delete a project."""
        return await self.repo.delete(project_id)

    async def get_all_themes(self) -> list[dict]:
        """Return unique themes across all projects and resources, with colors."""
        all_themes: set[str] = set()
        # From projects
        result = await self.db.execute(select(Project.themes))
        for (themes_list,) in result:
            if themes_list:
                for t in themes_list:
                    if t:
                        all_themes.add(t)
        # From resources
        res_result = await self.db.execute(select(Resource.themes))
        for (themes_list,) in res_result:
            if themes_list:
                for t in themes_list:
                    if t:
                        all_themes.add(t)
        sorted_themes = sorted(all_themes)

        # Fetch existing colors
        color_result = await self.db.execute(select(ThemeColor))
        color_map = {tc.name: tc.color for tc in color_result.scalars().all()}

        # Auto-create colors for new themes
        idx = len(color_map)
        out = []
        for t in sorted_themes:
            if t not in color_map:
                color = _DEFAULT_PALETTE[idx % len(_DEFAULT_PALETTE)]
                tc = ThemeColor(name=t, color=color)
                self.db.add(tc)
                color_map[t] = color
                idx += 1
            out.append({"name": t, "color": color_map[t]})
        await self.db.flush()
        return out

    async def get_theme_color(self, theme_name: str) -> str | None:
        """Return the color for a specific theme."""
        result = await self.db.execute(
            select(ThemeColor).where(ThemeColor.name == theme_name)
        )
        tc = result.scalar_one_or_none()
        return tc.color if tc else None

    async def set_theme_color(self, theme_name: str, color: str) -> dict:
        """Set/update the color for a theme."""
        result = await self.db.execute(
            select(ThemeColor).where(ThemeColor.name == theme_name)
        )
        tc = result.scalar_one_or_none()
        if tc:
            tc.color = color
        else:
            tc = ThemeColor(name=theme_name, color=color)
            self.db.add(tc)
        await self.db.flush()
        return {"name": theme_name, "color": color}

    async def rename_theme(self, old_name: str, new_name: str) -> int:
        """Rename a theme across all projects and resources, and update the color mapping."""
        count = 0
        # Rename in projects
        result = await self.db.execute(select(Project))
        projects = list(result.scalars().all())
        for proj in projects:
            if proj.themes and old_name in proj.themes:
                new_themes = [new_name if t == old_name else t for t in proj.themes]
                seen = set()
                deduped = []
                for t in new_themes:
                    if t not in seen:
                        seen.add(t)
                        deduped.append(t)
                await self.repo.update(proj.id, themes=deduped)
                count += 1
        # Rename in resources
        res_result = await self.db.execute(select(Resource))
        resources = list(res_result.scalars().all())
        for res in resources:
            if res.themes and old_name in res.themes:
                new_themes = [new_name if t == old_name else t for t in res.themes]
                seen = set()
                deduped = []
                for t in new_themes:
                    if t not in seen:
                        seen.add(t)
                        deduped.append(t)
                res.themes = deduped
                count += 1
        await self.db.flush()
        # Rename the color mapping too
        color_result = await self.db.execute(
            select(ThemeColor).where(ThemeColor.name == old_name)
        )
        old_tc = color_result.scalar_one_or_none()
        if old_tc:
            old_color = old_tc.color
            await self.db.delete(old_tc)
            await self.db.flush()
            # Check if new name already has a color
            new_result = await self.db.execute(
                select(ThemeColor).where(ThemeColor.name == new_name)
            )
            if not new_result.scalar_one_or_none():
                self.db.add(ThemeColor(name=new_name, color=old_color))
                await self.db.flush()
        return count
