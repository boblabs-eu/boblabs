"""Bob Manager — AI Orchestrator repositories."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orchestrator import (
    AIAgent,
    AIModel,
    AIProvider,
    Conversation,
    GpuLock,
    Message,
    OrchestratorSettings,
    OrchestratorTask,
)


# ── Settings ──────────────────────────────────────


class OrchestratorSettingsRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self) -> OrchestratorSettings | None:
        result = await self.db.execute(
            select(OrchestratorSettings).where(OrchestratorSettings.id == 1)
        )
        return result.scalar_one_or_none()

    async def upsert(self, **kwargs) -> OrchestratorSettings:
        settings = await self.get()
        if settings is None:
            settings = OrchestratorSettings(id=1, **kwargs)
            self.db.add(settings)
        else:
            await self.db.execute(
                update(OrchestratorSettings)
                .where(OrchestratorSettings.id == 1)
                .values(**kwargs)
            )
        await self.db.flush()
        return await self.get()  # type: ignore[return-value]


# ── AI Providers ──────────────────────────────────


class AIProviderRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, active_only: bool = False) -> list[AIProvider]:
        q = select(AIProvider).order_by(AIProvider.name)
        if active_only:
            q = q.where(AIProvider.is_active.is_(True))
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def get_by_id(self, provider_id: UUID) -> AIProvider | None:
        result = await self.db.execute(
            select(AIProvider).where(AIProvider.id == provider_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> AIProvider | None:
        result = await self.db.execute(
            select(AIProvider).where(AIProvider.name == name)
        )
        return result.scalar_one_or_none()

    async def create(self, provider: AIProvider) -> AIProvider:
        self.db.add(provider)
        await self.db.flush()
        await self.db.refresh(provider)
        return provider

    async def update(self, provider_id: UUID, **kwargs) -> AIProvider | None:
        await self.db.execute(
            update(AIProvider).where(AIProvider.id == provider_id).values(**kwargs)
        )
        await self.db.flush()
        return await self.get_by_id(provider_id)

    async def delete(self, provider_id: UUID) -> bool:
        provider = await self.get_by_id(provider_id)
        if provider:
            await self.db.delete(provider)
            await self.db.flush()
            return True
        return False


# ── AI Models ─────────────────────────────────────


class AIModelRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, provider_id: UUID | None = None) -> list[AIModel]:
        q = select(AIModel).order_by(AIModel.name)
        if provider_id:
            q = q.where(AIModel.provider_id == provider_id)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def get_by_id(self, model_id: UUID) -> AIModel | None:
        result = await self.db.execute(
            select(AIModel).where(AIModel.id == model_id)
        )
        return result.scalar_one_or_none()

    async def get_by_provider_and_identifier(
        self, provider_id: UUID, model_identifier: str
    ) -> AIModel | None:
        result = await self.db.execute(
            select(AIModel).where(
                AIModel.provider_id == provider_id,
                AIModel.model_identifier == model_identifier,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self, provider_id: UUID, model_identifier: str, name: str, **kwargs
    ) -> AIModel:
        existing = await self.get_by_provider_and_identifier(
            provider_id, model_identifier
        )
        now = datetime.now(timezone.utc)
        if existing:
            await self.db.execute(
                update(AIModel)
                .where(AIModel.id == existing.id)
                .values(
                    name=name,
                    is_available=True,
                    last_seen_at=now,
                    **kwargs,
                )
            )
            await self.db.flush()
            return await self.get_by_id(existing.id)  # type: ignore[return-value]
        else:
            model = AIModel(
                provider_id=provider_id,
                model_identifier=model_identifier,
                name=name,
                is_available=True,
                last_seen_at=now,
                **kwargs,
            )
            self.db.add(model)
            await self.db.flush()
            await self.db.refresh(model)
            return model

    async def mark_unavailable(self, provider_id: UUID, exclude_ids: list[UUID]):
        """Mark models not in exclude_ids as unavailable (stale discovery)."""
        await self.db.execute(
            update(AIModel)
            .where(
                AIModel.provider_id == provider_id,
                AIModel.id.notin_(exclude_ids),
            )
            .values(is_available=False)
        )
        await self.db.flush()

    async def mark_all_unavailable_for_server(self, server_id: UUID):
        """Mark all models from providers linked to a server as unavailable (agent offline)."""
        provider_ids = await self.db.execute(
            select(AIProvider.id).where(AIProvider.server_id == server_id)
        )
        pids = [row[0] for row in provider_ids.fetchall()]
        if pids:
            await self.db.execute(
                update(AIModel)
                .where(AIModel.provider_id.in_(pids))
                .values(is_available=False)
            )
            await self.db.flush()


# ── AI Agents ─────────────────────────────────────


class AIAgentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, active_only: bool = False) -> list[AIAgent]:
        q = select(AIAgent).order_by(AIAgent.name)
        if active_only:
            q = q.where(AIAgent.is_active.is_(True))
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def get_by_id(self, agent_id: UUID) -> AIAgent | None:
        result = await self.db.execute(
            select(AIAgent).where(AIAgent.id == agent_id)
        )
        return result.scalar_one_or_none()

    async def create(self, agent: AIAgent) -> AIAgent:
        self.db.add(agent)
        await self.db.flush()
        await self.db.refresh(agent)
        return agent

    async def update(self, agent_id: UUID, **kwargs) -> AIAgent | None:
        await self.db.execute(
            update(AIAgent).where(AIAgent.id == agent_id).values(**kwargs)
        )
        await self.db.flush()
        return await self.get_by_id(agent_id)

    async def delete(self, agent_id: UUID) -> bool:
        agent = await self.get_by_id(agent_id)
        if agent:
            await self.db.delete(agent)
            await self.db.flush()
            return True
        return False


# ── Conversations ─────────────────────────────────


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, status: str | None = None) -> list[Conversation]:
        q = select(Conversation).order_by(Conversation.updated_at.desc())
        if status:
            q = q.where(Conversation.status == status)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def get_by_id(self, conv_id: UUID) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        return result.scalar_one_or_none()

    async def create(self, conv: Conversation) -> Conversation:
        self.db.add(conv)
        await self.db.flush()
        await self.db.refresh(conv)
        return conv

    async def update(self, conv_id: UUID, **kwargs) -> Conversation | None:
        await self.db.execute(
            update(Conversation).where(Conversation.id == conv_id).values(**kwargs)
        )
        await self.db.flush()
        return await self.get_by_id(conv_id)

    async def delete(self, conv_id: UUID) -> bool:
        conv = await self.get_by_id(conv_id)
        if conv:
            await self.db.delete(conv)
            await self.db.flush()
            return True
        return False


# ── Messages ──────────────────────────────────────


class MessageRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_conversation(
        self, conv_id: UUID, limit: int = 200
    ) -> list[Message]:
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create(self, msg: Message) -> Message:
        self.db.add(msg)
        await self.db.flush()
        await self.db.refresh(msg)
        return msg

    async def update(self, msg_id: UUID, **kwargs) -> Message | None:
        await self.db.execute(
            update(Message).where(Message.id == msg_id).values(**kwargs)
        )
        await self.db.flush()
        result = await self.db.execute(
            select(Message).where(Message.id == msg_id)
        )
        return result.scalar_one_or_none()


# ── Orchestrator Tasks ────────────────────────────


class TaskRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_queued(self, limit: int = 10) -> list[OrchestratorTask]:
        result = await self.db.execute(
            select(OrchestratorTask)
            .where(OrchestratorTask.status == "queued")
            .order_by(
                OrchestratorTask.priority.desc(),
                OrchestratorTask.queued_at,
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, task_id: UUID) -> OrchestratorTask | None:
        result = await self.db.execute(
            select(OrchestratorTask).where(OrchestratorTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_by_conversation(
        self, conv_id: UUID, limit: int = 50
    ) -> list[OrchestratorTask]:
        result = await self.db.execute(
            select(OrchestratorTask)
            .where(OrchestratorTask.conversation_id == conv_id)
            .order_by(OrchestratorTask.queued_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_recent(
        self, limit: int = 50, conversation_id: UUID | None = None
    ) -> list[OrchestratorTask]:
        q = select(OrchestratorTask).order_by(OrchestratorTask.queued_at.desc())
        if conversation_id:
            q = q.where(OrchestratorTask.conversation_id == conversation_id)
        result = await self.db.execute(q.limit(limit))
        return list(result.scalars().all())

    async def create(self, task: OrchestratorTask) -> OrchestratorTask:
        self.db.add(task)
        await self.db.flush()
        await self.db.refresh(task)
        return task

    async def update(self, task_id: UUID, **kwargs) -> OrchestratorTask | None:
        await self.db.execute(
            update(OrchestratorTask)
            .where(OrchestratorTask.id == task_id)
            .values(**kwargs)
        )
        await self.db.flush()
        return await self.get_by_id(task_id)


# ── GPU Locks ─────────────────────────────────────


class GpuLockRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def acquire(
        self, server_id: UUID, gpu_index: int, task_id: UUID
    ) -> bool:
        """Try to acquire a GPU lock. Returns True if successful."""
        existing = await self.db.execute(
            select(GpuLock).where(
                GpuLock.server_id == server_id,
                GpuLock.gpu_index == gpu_index,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return False
        lock = GpuLock(server_id=server_id, gpu_index=gpu_index, task_id=task_id)
        self.db.add(lock)
        await self.db.flush()
        return True

    async def release(self, server_id: UUID, gpu_index: int) -> None:
        await self.db.execute(
            delete(GpuLock).where(
                GpuLock.server_id == server_id,
                GpuLock.gpu_index == gpu_index,
            )
        )
        await self.db.flush()

    async def release_by_task(self, task_id: UUID) -> None:
        await self.db.execute(
            delete(GpuLock).where(GpuLock.task_id == task_id)
        )
        await self.db.flush()

    async def get_locked_gpus(self, server_id: UUID) -> list[int]:
        result = await self.db.execute(
            select(GpuLock.gpu_index).where(GpuLock.server_id == server_id)
        )
        return [row[0] for row in result.all()]

    async def get_all_locks(self) -> list[GpuLock]:
        result = await self.db.execute(select(GpuLock))
        return list(result.scalars().all())
