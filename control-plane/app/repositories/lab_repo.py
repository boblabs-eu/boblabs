"""Bob Manager — Lab repository layer."""

import re
import uuid
from datetime import datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.authorization import filter_query_by_access, get_default_acl
from app.models.orchestrator import (
    CronJob,
    Lab,
    LabAgent,
    LabMemory,
    LabMessage,
    LabResource,
    LabScheduleLog,
    LabTool,
    LibraryAgent,
    PromptTemplate,
    ToolSet,
)

# Characters that asyncpg / PostgreSQL rejects: NULL bytes, lone surrogates
_BAD_CHARS = re.compile(r"[\x00\ud800-\udfff]")


def _sanitize(text: str | None) -> str | None:
    """Strip characters that PostgreSQL / asyncpg cannot store."""
    if text is None:
        return None
    return _BAD_CHARS.sub("\ufffd", text)


def _sanitize_json(obj):
    """Recursively sanitize strings inside a JSON-serializable object."""
    if isinstance(obj, str):
        return _BAD_CHARS.sub("\ufffd", obj)
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_json(v) for v in obj]
    return obj


class LibraryAgentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> list[LibraryAgent]:
        result = await self.db.execute(
            select(LibraryAgent).order_by(LibraryAgent.name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, agent_id: uuid.UUID) -> LibraryAgent | None:
        result = await self.db.execute(select(LibraryAgent).where(LibraryAgent.id == agent_id))
        return result.scalars().first()

    async def create(self, **kwargs) -> LibraryAgent:
        agent = LibraryAgent(**kwargs)
        self.db.add(agent)
        await self.db.flush()
        await self.db.refresh(agent)
        return agent

    async def update(self, agent_id: uuid.UUID, **kwargs) -> LibraryAgent | None:
        stmt = update(LibraryAgent).where(LibraryAgent.id == agent_id).values(**kwargs)
        await self.db.execute(stmt)
        await self.db.flush()
        return await self.get_by_id(agent_id)

    async def delete(self, agent_id: uuid.UUID) -> None:
        await self.db.execute(delete(LibraryAgent).where(LibraryAgent.id == agent_id))
        await self.db.flush()


class PromptTemplateRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> list[PromptTemplate]:
        result = await self.db.execute(
            select(PromptTemplate).order_by(PromptTemplate.name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, pt_id: uuid.UUID) -> PromptTemplate | None:
        result = await self.db.execute(select(PromptTemplate).where(PromptTemplate.id == pt_id))
        return result.scalars().first()

    async def create(self, **kwargs) -> PromptTemplate:
        pt = PromptTemplate(**kwargs)
        self.db.add(pt)
        await self.db.flush()
        await self.db.refresh(pt)
        return pt

    async def update(self, pt_id: uuid.UUID, **kwargs) -> PromptTemplate | None:
        stmt = update(PromptTemplate).where(PromptTemplate.id == pt_id).values(**kwargs)
        await self.db.execute(stmt)
        await self.db.flush()
        return await self.get_by_id(pt_id)

    async def delete(self, pt_id: uuid.UUID) -> None:
        await self.db.execute(delete(PromptTemplate).where(PromptTemplate.id == pt_id))
        await self.db.flush()


class CronJobRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> list[CronJob]:
        result = await self.db.execute(
            select(CronJob).order_by(CronJob.name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, cj_id: uuid.UUID) -> CronJob | None:
        result = await self.db.execute(select(CronJob).where(CronJob.id == cj_id))
        return result.scalars().first()

    async def create(self, **kwargs) -> CronJob:
        cj = CronJob(**kwargs)
        self.db.add(cj)
        await self.db.flush()
        await self.db.refresh(cj)
        return cj

    async def update(self, cj_id: uuid.UUID, **kwargs) -> CronJob | None:
        stmt = update(CronJob).where(CronJob.id == cj_id).values(**kwargs)
        await self.db.execute(stmt)
        await self.db.flush()
        return await self.get_by_id(cj_id)

    async def delete(self, cj_id: uuid.UUID) -> None:
        await self.db.execute(delete(CronJob).where(CronJob.id == cj_id))
        await self.db.flush()

    async def get_labs_using(self, cj_id: uuid.UUID) -> list[dict]:
        """Return labs that reference this cron job in their cron_job_ids."""
        result = await self.db.execute(select(Lab))
        labs = result.scalars().all()
        using = []
        for lab in labs:
            ids = lab.cron_job_ids or []
            if str(cj_id) in [str(i) for i in ids]:
                using.append({"id": str(lab.id), "name": lab.name, "status": lab.status})
        return using


class ToolSetRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> list[ToolSet]:
        result = await self.db.execute(
            select(ToolSet).order_by(ToolSet.name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, ts_id: uuid.UUID) -> ToolSet | None:
        result = await self.db.execute(select(ToolSet).where(ToolSet.id == ts_id))
        return result.scalars().first()

    async def create(self, **kwargs) -> ToolSet:
        ts = ToolSet(**kwargs)
        self.db.add(ts)
        await self.db.flush()
        await self.db.refresh(ts)
        return ts

    async def update(self, ts_id: uuid.UUID, **kwargs) -> ToolSet | None:
        stmt = update(ToolSet).where(ToolSet.id == ts_id).values(**kwargs)
        await self.db.execute(stmt)
        await self.db.flush()
        return await self.get_by_id(ts_id)

    async def delete(self, ts_id: uuid.UUID) -> None:
        await self.db.execute(delete(ToolSet).where(ToolSet.id == ts_id))
        await self.db.flush()


class LabRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self, user: dict | None = None) -> list[Lab]:
        query = select(Lab).order_by(Lab.updated_at.desc())
        if user:
            query = filter_query_by_access(query, Lab, user)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, lab_id: uuid.UUID) -> Lab | None:
        result = await self.db.execute(select(Lab).where(Lab.id == lab_id))
        return result.scalars().first()

    async def create(self, user: dict | None = None, **kwargs) -> Lab:
        if user and "acl" not in kwargs:
            kwargs["acl"] = get_default_acl(user.get("sub", "admin"))
        lab = Lab(**kwargs)
        self.db.add(lab)
        await self.db.flush()
        await self.db.refresh(lab)
        return lab

    async def update(self, lab_id: uuid.UUID, **kwargs) -> Lab | None:
        stmt = update(Lab).where(Lab.id == lab_id).values(**kwargs)
        await self.db.execute(stmt)
        await self.db.flush()
        return await self.get_by_id(lab_id)

    async def delete(self, lab_id: uuid.UUID) -> None:
        await self.db.execute(delete(Lab).where(Lab.id == lab_id))
        await self.db.flush()


class LabAgentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_lab(self, lab_id: uuid.UUID, active_only: bool = False) -> list[LabAgent]:
        stmt = select(LabAgent).where(LabAgent.lab_id == lab_id)
        if active_only:
            stmt = stmt.where(LabAgent.is_active == True)
        stmt = stmt.order_by(LabAgent.sort_order)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_all(self) -> list[LabAgent]:
        """Return all agents across all labs (for agent library)."""
        result = await self.db.execute(
            select(LabAgent).order_by(LabAgent.name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, agent_id: uuid.UUID) -> LabAgent | None:
        result = await self.db.execute(select(LabAgent).where(LabAgent.id == agent_id))
        return result.scalars().first()

    async def get_by_name(self, lab_id: uuid.UUID, name: str) -> LabAgent | None:
        result = await self.db.execute(
            select(LabAgent).where(LabAgent.lab_id == lab_id, LabAgent.name == name)
        )
        return result.scalars().first()

    async def create(self, **kwargs) -> LabAgent:
        agent = LabAgent(**kwargs)
        self.db.add(agent)
        await self.db.flush()
        await self.db.refresh(agent)
        return agent

    async def update(self, agent_id: uuid.UUID, **kwargs) -> LabAgent | None:
        stmt = update(LabAgent).where(LabAgent.id == agent_id).values(**kwargs)
        await self.db.execute(stmt)
        await self.db.flush()
        return await self.get_by_id(agent_id)

    async def delete(self, agent_id: uuid.UUID) -> None:
        await self.db.execute(delete(LabAgent).where(LabAgent.id == agent_id))
        await self.db.flush()


class LabToolRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_lab(self, lab_id: uuid.UUID) -> list[LabTool]:
        result = await self.db.execute(
            select(LabTool).where(LabTool.lab_id == lab_id).order_by(LabTool.name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, tool_id: uuid.UUID) -> LabTool | None:
        result = await self.db.execute(select(LabTool).where(LabTool.id == tool_id))
        return result.scalars().first()

    async def create(self, **kwargs) -> LabTool:
        tool = LabTool(**kwargs)
        self.db.add(tool)
        await self.db.flush()
        await self.db.refresh(tool)
        return tool

    async def update(self, tool_id: uuid.UUID, **kwargs) -> LabTool | None:
        stmt = update(LabTool).where(LabTool.id == tool_id).values(**kwargs)
        await self.db.execute(stmt)
        await self.db.flush()
        return await self.get_by_id(tool_id)

    async def delete(self, tool_id: uuid.UUID) -> None:
        await self.db.execute(delete(LabTool).where(LabTool.id == tool_id))
        await self.db.flush()


class LabMessageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_lab(
        self,
        lab_id: uuid.UUID,
        limit: int = 200,
        iteration: int | None = None,
        sender_agent_id: uuid.UUID | None = None,
        include_targeting: bool = False,
    ) -> list[LabMessage]:
        stmt = select(LabMessage).where(LabMessage.lab_id == lab_id)
        if iteration is not None:
            stmt = stmt.where(LabMessage.iteration == iteration)
        if sender_agent_id is not None:
            if include_targeting:
                stmt = stmt.where(
                    or_(
                        LabMessage.sender_agent_id == sender_agent_id,
                        LabMessage.target_agent_id == sender_agent_id,
                    )
                )
            else:
                stmt = stmt.where(LabMessage.sender_agent_id == sender_agent_id)
        stmt = stmt.order_by(LabMessage.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(reversed(result.scalars().all()))

    async def get_recent(self, lab_id: uuid.UUID, limit: int = 50) -> list[LabMessage]:
        stmt = (
            select(LabMessage)
            .where(LabMessage.lab_id == lab_id)
            .order_by(LabMessage.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(reversed(result.scalars().all()))

    async def create(self, **kwargs) -> LabMessage:
        if "content" in kwargs:
            kwargs["content"] = _sanitize(kwargs["content"]) or ""
        for jsonb_field in ("tool_input", "tool_output", "extra"):
            if jsonb_field in kwargs and kwargs[jsonb_field] is not None:
                kwargs[jsonb_field] = _sanitize_json(kwargs[jsonb_field])
        msg = LabMessage(**kwargs)
        self.db.add(msg)
        await self.db.flush()
        await self.db.refresh(msg)
        return msg

    async def get_injections(self, lab_id: uuid.UUID, since: datetime | None = None) -> list[LabMessage]:
        stmt = select(LabMessage).where(
            LabMessage.lab_id == lab_id,
            LabMessage.message_type == "inject",
        )
        if since:
            stmt = stmt.where(LabMessage.created_at > since)
        stmt = stmt.order_by(LabMessage.created_at)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_lab(self, lab_id: uuid.UUID) -> None:
        await self.db.execute(delete(LabMessage).where(LabMessage.lab_id == lab_id))
        await self.db.flush()


class LabMemoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_lab(
        self, lab_id: uuid.UUID, scope: str | None = None, limit: int = 50,
        agent_id: uuid.UUID | None = None,
    ) -> list[LabMemory]:
        stmt = select(LabMemory).where(LabMemory.lab_id == lab_id)
        if scope:
            stmt = stmt.where(LabMemory.scope == scope)
        if agent_id is not None:
            stmt = stmt.where(LabMemory.agent_id == agent_id)
        stmt = stmt.order_by(LabMemory.importance.desc(), LabMemory.updated_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_agent(self, agent_id: uuid.UUID, limit: int = 30) -> list[LabMemory]:
        stmt = (
            select(LabMemory)
            .where(LabMemory.agent_id == agent_id, LabMemory.scope == "agent")
            .order_by(LabMemory.importance.desc(), LabMemory.updated_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_all_memories(self, limit: int = 30) -> list[LabMemory]:
        """Return memories across ALL labs (for shared memory agents)."""
        stmt = (
            select(LabMemory)
            .order_by(LabMemory.importance.desc(), LabMemory.updated_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create(self, **kwargs) -> LabMemory:
        if "content" in kwargs:
            kwargs["content"] = _sanitize(kwargs["content"]) or ""
        mem = LabMemory(**kwargs)
        self.db.add(mem)
        await self.db.flush()
        await self.db.refresh(mem)
        return mem

    async def delete(self, memory_id: uuid.UUID) -> None:
        await self.db.execute(delete(LabMemory).where(LabMemory.id == memory_id))
        await self.db.flush()

    async def delete_by_lab(self, lab_id: uuid.UUID) -> None:
        await self.db.execute(delete(LabMemory).where(LabMemory.lab_id == lab_id))
        await self.db.flush()


class LabResourceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_lab(self, lab_id: uuid.UUID) -> list[LabResource]:
        result = await self.db.execute(
            select(LabResource).where(LabResource.lab_id == lab_id).order_by(LabResource.created_at)
        )
        return list(result.scalars().all())

    async def get_by_id(self, resource_id: uuid.UUID) -> LabResource | None:
        result = await self.db.execute(select(LabResource).where(LabResource.id == resource_id))
        return result.scalars().first()

    async def create(self, **kwargs) -> LabResource:
        res = LabResource(**kwargs)
        self.db.add(res)
        await self.db.flush()
        await self.db.refresh(res)
        return res

    async def delete(self, resource_id: uuid.UUID) -> None:
        await self.db.execute(delete(LabResource).where(LabResource.id == resource_id))
        await self.db.flush()

    async def delete_by_lab(self, lab_id: uuid.UUID) -> None:
        await self.db.execute(delete(LabResource).where(LabResource.lab_id == lab_id))
        await self.db.flush()


class LabScheduleLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> LabScheduleLog:
        log = LabScheduleLog(**kwargs)
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)
        return log

    async def update(self, log_id: uuid.UUID, **kwargs) -> None:
        stmt = update(LabScheduleLog).where(LabScheduleLog.id == log_id).values(**kwargs)
        await self.db.execute(stmt)
        await self.db.flush()
