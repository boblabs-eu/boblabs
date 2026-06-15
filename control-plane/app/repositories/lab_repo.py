"""Bob Manager — Lab repository layer."""

import uuid
from datetime import datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
    McpServer,
    PromptTemplate,
    ToolSet,
)
from app.repositories._paginate import MAX_LIMIT, clamp_limit

# D05 — shared sanitiser moved to app.repositories._sanitize so every
# repo gets the same NULL-byte / lone-surrogate handling. Aliased back
# to the old private names so existing call sites keep working.
from app.repositories._sanitize import (
    sanitize_json as _sanitize_json,
)
from app.repositories._sanitize import (
    sanitize_text as _sanitize,
)
from app.services.authorization import filter_query_by_access, get_default_acl


class LibraryAgentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> list[LibraryAgent]:
        result = await self.db.execute(select(LibraryAgent).order_by(LibraryAgent.name))
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
        result = await self.db.execute(select(PromptTemplate).order_by(PromptTemplate.name))
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
        result = await self.db.execute(select(CronJob).order_by(CronJob.name))
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
        """Return labs that reference this cron job in their cron_job_ids.

        P01 — previously loaded every Lab row and filtered in Python
        (linear in lab count). Now uses a JSONB containment query
        (``cron_job_ids @> [cj_id]``) so Postgres does the filter
        server-side and a GIN index on ``cron_job_ids`` (if added)
        makes it sub-millisecond.
        """
        # Bind the cron-job UUID as a JSONB string element. The cron_job_ids
        # column stores entries as strings (the model defaults to a JSONB
        # list of stringified UUIDs); use the @> containment operator so
        # the query plan can use a GIN index if one is created.
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import JSONB

        result = await self.db.execute(
            select(Lab.id, Lab.name, Lab.status).where(
                Lab.cron_job_ids.op("@>")(cast([str(cj_id)], JSONB))
            )
        )
        return [{"id": str(row.id), "name": row.name, "status": row.status} for row in result.all()]


class ToolSetRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> list[ToolSet]:
        result = await self.db.execute(select(ToolSet).order_by(ToolSet.name))
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


class McpServerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> list[McpServer]:
        result = await self.db.execute(select(McpServer).order_by(McpServer.name))
        return list(result.scalars().all())

    async def get_by_id(self, server_id: uuid.UUID) -> McpServer | None:
        result = await self.db.execute(select(McpServer).where(McpServer.id == server_id))
        return result.scalars().first()

    async def get_by_slug(self, slug: str) -> McpServer | None:
        result = await self.db.execute(select(McpServer).where(McpServer.slug == slug))
        return result.scalars().first()

    async def get_by_name(self, name: str) -> McpServer | None:
        result = await self.db.execute(select(McpServer).where(McpServer.name == name))
        return result.scalars().first()

    async def create(self, **kwargs) -> McpServer:
        server = McpServer(**kwargs)
        self.db.add(server)
        await self.db.flush()
        await self.db.refresh(server)
        return server

    async def update(self, server_id: uuid.UUID, **kwargs) -> McpServer | None:
        stmt = update(McpServer).where(McpServer.id == server_id).values(**kwargs)
        await self.db.execute(stmt)
        await self.db.flush()
        return await self.get_by_id(server_id)

    async def delete(self, server_id: uuid.UUID) -> None:
        await self.db.execute(delete(McpServer).where(McpServer.id == server_id))
        await self.db.flush()


class LabRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(
        self,
        user: dict | None = None,
        limit: int = MAX_LIMIT,
        offset: int = 0,
    ) -> list[Lab]:
        # P01/P04 — bound the unfiltered scan; the Labs UI typically
        # paginates client-side, so MAX_LIMIT is generous enough.
        query = select(Lab).order_by(Lab.updated_at.desc())
        if user:
            query = filter_query_by_access(query, Lab, user)
        query = query.limit(clamp_limit(limit)).offset(max(0, offset))
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

    async def get_all(
        self,
        user: dict | None = None,
        limit: int = MAX_LIMIT,
        offset: int = 0,
    ) -> list[LabAgent]:
        """Return all agents across all labs (for the agent library UI).

        P06 — accepts an optional ``user`` and filters to agents whose
        parent lab is ACL-visible to that user. Admin / no-user gets
        every agent (legacy behavior preserved for the existing
        unauth'd /labs/agents/library route, which is tracked in
        ``KNOWN_OPEN_ROUTES`` until Session 5 adds auth). Once the
        route is gated, callers should pass ``user=user`` to enforce
        ACL filtering at the SQL layer.
        """
        stmt = select(LabAgent).order_by(LabAgent.name)
        if user is not None and user.get("role") != "admin":
            # Restrict to agents whose lab the caller can VIEW.
            visible_lab_ids = await self.db.execute(
                filter_query_by_access(select(Lab.id), Lab, user)
            )
            ids = [row[0] for row in visible_lab_ids.all()]
            if not ids:
                return []
            stmt = stmt.where(LabAgent.lab_id.in_(ids))
        stmt = stmt.limit(clamp_limit(limit)).offset(max(0, offset))
        result = await self.db.execute(stmt)
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
        # P05 — clamp caller-supplied limit so a malformed UI request
        # can't ask for the whole message table at once.
        stmt = stmt.order_by(LabMessage.created_at.desc()).limit(clamp_limit(limit))
        result = await self.db.execute(stmt)
        return list(reversed(result.scalars().all()))

    async def get_recent(self, lab_id: uuid.UUID, limit: int = 50) -> list[LabMessage]:
        stmt = (
            select(LabMessage)
            .where(LabMessage.lab_id == lab_id)
            .order_by(LabMessage.created_at.desc())
            .limit(clamp_limit(limit))
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

    async def get_injections(
        self,
        lab_id: uuid.UUID,
        since: datetime | None = None,
        limit: int = MAX_LIMIT,
    ) -> list[LabMessage]:
        # P03 — was unbounded; an adversarial inject loop could materialise
        # tens of thousands of rows into memory in one call. Cap at
        # MAX_LIMIT and let the caller paginate via the `since` cursor if
        # they need more.
        stmt = select(LabMessage).where(
            LabMessage.lab_id == lab_id,
            LabMessage.message_type == "inject",
        )
        if since:
            stmt = stmt.where(LabMessage.created_at > since)
        stmt = stmt.order_by(LabMessage.created_at).limit(clamp_limit(limit))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_lab(self, lab_id: uuid.UUID) -> None:
        await self.db.execute(delete(LabMessage).where(LabMessage.lab_id == lab_id))
        await self.db.flush()


class LabMemoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_lab(
        self,
        lab_id: uuid.UUID,
        scope: str | None = None,
        limit: int = 50,
        agent_id: uuid.UUID | None = None,
    ) -> list[LabMemory]:
        stmt = select(LabMemory).where(LabMemory.lab_id == lab_id)
        if scope:
            stmt = stmt.where(LabMemory.scope == scope)
        if agent_id is not None:
            stmt = stmt.where(LabMemory.agent_id == agent_id)
        stmt = stmt.order_by(
            LabMemory.importance.desc(),
            LabMemory.updated_at.desc(),
        ).limit(clamp_limit(limit))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_agent(self, agent_id: uuid.UUID, limit: int = 30) -> list[LabMemory]:
        stmt = (
            select(LabMemory)
            .where(LabMemory.agent_id == agent_id, LabMemory.scope == "agent")
            .order_by(LabMemory.importance.desc(), LabMemory.updated_at.desc())
            .limit(clamp_limit(limit))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_all_memories(
        self,
        *,
        caller_lab_id: uuid.UUID,
        share_memory_confirmed: bool,
        limit: int = 30,
    ) -> list[LabMemory]:
        """Return memories across ALL labs (for shared memory agents).

        A03 — cross-lab memory leak path. The caller MUST:
          1. Pass ``caller_lab_id`` so the operation is traceable in
             logs / future audit (and a refactor that drops the arg
             fails at call sites loudly).
          2. Pass ``share_memory_confirmed=True`` to attest that the
             calling agent has its ``share_memory=True`` flag set
             (or the parent lab's ``share_memory_override`` is True).

        Calls without ``share_memory_confirmed`` raise — bypassing the
        check is a documented data-leak vector.

        The keyword-only signature (``*,``) prevents the typical "drop
        the second positional arg and lose the guard" refactor mistake.
        """
        if not share_memory_confirmed:
            raise PermissionError(
                f"get_all_memories called from lab={caller_lab_id} without "
                "share_memory_confirmed=True. Either the calling agent must "
                "have share_memory=True (or the lab's share_memory_override) "
                "or the caller must use get_by_lab(lab_id) instead. "
                "Cluster A03 — cross-lab leak path."
            )
        stmt = (
            select(LabMemory)
            .order_by(LabMemory.importance.desc(), LabMemory.updated_at.desc())
            .limit(clamp_limit(limit))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create(self, **kwargs) -> LabMemory:
        # D05 — sanitise every text field the model exposes, matching
        # what LabMessageRepository.create already does. The pre-fix
        # version only stripped `content`, so an agent injecting a
        # NULL byte into `key` would crash asyncpg at flush time.
        for text_field in ("content", "key"):
            if text_field in kwargs:
                kwargs[text_field] = _sanitize(kwargs[text_field]) or ""
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
