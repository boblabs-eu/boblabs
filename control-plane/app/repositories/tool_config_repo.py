"""Repository for tool configuration (SMTP, Twitter API keys, etc.)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orchestrator import ToolConfig


class ToolConfigRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_tool_type(self, tool_type: str) -> ToolConfig | None:
        result = await self.db.execute(select(ToolConfig).where(ToolConfig.tool_type == tool_type))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[ToolConfig]:
        result = await self.db.execute(select(ToolConfig).order_by(ToolConfig.tool_type))
        return list(result.scalars().all())

    async def upsert(self, tool_type: str, config: dict) -> ToolConfig:
        existing = await self.get_by_tool_type(tool_type)
        if existing:
            existing.config = config
            await self.db.flush()
            return existing
        tc = ToolConfig(tool_type=tool_type, config=config)
        self.db.add(tc)
        await self.db.flush()
        return tc

    async def delete(self, tool_type: str) -> bool:
        existing = await self.get_by_tool_type(tool_type)
        if not existing:
            return False
        await self.db.delete(existing)
        await self.db.flush()
        return True
