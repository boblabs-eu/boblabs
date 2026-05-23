"""Bob Manager — Conversation service.

Handles conversation CRUD and message management.
"""

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orchestrator import Conversation, Message
from app.repositories.orchestrator_repo import ConversationRepository, MessageRepository
from app.schemas.orchestrator import ConversationCreate, ConversationUpdate
from app.services.authorization import filter_query_by_access, get_default_acl

logger = logging.getLogger(__name__)


class ConversationService:
    """Business logic for conversation management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.conv_repo = ConversationRepository(db)
        self.msg_repo = MessageRepository(db)

    async def list_conversations(self, status: str | None = None, user: dict | None = None) -> list[dict]:
        """Return conversations visible to user, with last message preview and count."""
        q = select(Conversation).order_by(Conversation.updated_at.desc())
        if status:
            q = q.where(Conversation.status == status)
        if user:
            q = filter_query_by_access(q, Conversation, user)
        result = await self.db.execute(q)
        convs = list(result.scalars().all())
        result = []
        for c in convs:
            # Get message count + last message
            count_q = await self.db.execute(
                select(func.count(Message.id)).where(
                    Message.conversation_id == c.id
                )
            )
            count = count_q.scalar() or 0

            last_msg_q = await self.db.execute(
                select(Message.content, Message.role)
                .where(Message.conversation_id == c.id)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            last_row = last_msg_q.first()
            last_message = None
            if last_row:
                content = last_row[0] or ""
                last_message = content[:120] + ("..." if len(content) > 120 else "")

            result.append(
                {
                    "id": c.id,
                    "title": c.title,
                    "status": c.status,
                    "agent_id": c.agent_id,
                    "tools": c.tools or [],
                    "created_at": c.created_at,
                    "updated_at": c.updated_at,
                    "last_message": last_message,
                    "message_count": count,
                }
            )
        return result

    async def get_conversation(self, conv_id: UUID) -> Conversation | None:
        return await self.conv_repo.get_by_id(conv_id)

    async def create_conversation(self, data: ConversationCreate, user: dict | None = None) -> Conversation:
        conv = Conversation(title=data.title, agent_id=data.agent_id, tools=data.tools or [])
        if user:
            conv.acl = get_default_acl(user.get("sub", "admin"))
        return await self.conv_repo.create(conv)

    async def update_conversation(
        self, conv_id: UUID, data: ConversationUpdate
    ) -> Conversation | None:
        updates = data.model_dump(exclude_unset=True)
        if not updates:
            return await self.conv_repo.get_by_id(conv_id)
        return await self.conv_repo.update(conv_id, **updates)

    async def delete_conversation(self, conv_id: UUID) -> bool:
        return await self.conv_repo.delete(conv_id)

    async def get_messages(self, conv_id: UUID, limit: int = 200) -> list[Message]:
        return await self.msg_repo.get_by_conversation(conv_id, limit=limit)

    async def add_message(
        self,
        conv_id: UUID,
        role: str,
        content: str,
        **kwargs,
    ) -> Message:
        msg = Message(
            conversation_id=conv_id,
            role=role,
            content=content,
            **kwargs,
        )
        msg = await self.msg_repo.create(msg)

        # Auto-title conversation from first user message
        conv = await self.conv_repo.get_by_id(conv_id)
        if conv and conv.title == "New Conversation" and role == "user":
            title = content[:80] + ("..." if len(content) > 80 else "")
            await self.conv_repo.update(conv_id, title=title)

        # Touch conversation updated_at
        await self.conv_repo.update(conv_id)

        return msg
