from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.conversation import Conversation, Message
from app.repositories.base import BaseRepository


class ConversationRepository(BaseRepository[Conversation]):
    def __init__(self, db: AsyncSession):
        super().__init__(Conversation, db)

    async def create(
        self,
        user_sub: str,
        title: str | None = None,
        model_id: str | None = None,
        input_price_per_1k_tokens: float | None = None,
        output_price_per_1k_tokens: float | None = None,
    ) -> Conversation:
        conversation = Conversation(
            user_sub=user_sub,
            title=title,
            model_id=model_id,
            input_price_per_1k_tokens=input_price_per_1k_tokens,
            output_price_per_1k_tokens=output_price_per_1k_tokens,
        )
        self._db.add(conversation)
        await self._db.flush()
        return conversation

    async def get(self, conversation_id: UUID, user_sub: str) -> Conversation:
        result = await self._db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise NotFoundError(f"Conversation {conversation_id} not found")
        if conversation.user_sub != user_sub:
            raise ForbiddenError("Access denied")
        return conversation

    async def list_for_user(self, user_sub: str) -> list[Conversation]:
        result = await self._db.execute(
            select(Conversation)
            .where(Conversation.user_sub == user_sub)
            .order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get_messages(self, conversation_id: UUID) -> list[Message]:
        result = await self._db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        return list(result.scalars().all())

    async def add_message(self, conversation_id: UUID, role: str, content: str) -> Message:
        message = Message(conversation_id=conversation_id, role=role, content=content)
        self._db.add(message)
        await self._db.flush()
        return message

    async def list_public(self, limit: int = 20) -> list[Conversation]:
        result = await self._db.execute(
            select(Conversation)
            .where(Conversation.is_public.is_(True))
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def get_public(self, conversation_id: UUID) -> Conversation | None:
        result = await self._db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.is_public.is_(True)
            )
        )
        return result.scalar_one_or_none()

    async def set_is_public(self, conversation_id: UUID, user_sub: str, value: bool) -> Conversation:
        conversation = await self.get(conversation_id, user_sub)
        conversation.is_public = value
        await self._db.flush()
        # updated_at is server-generated (onupdate=func.now()) and expired by the flush; without a
        # refresh, serializing the row triggers a sync lazy load inside pydantic (MissingGreenlet,
        # 500 on PATCH — 2026-09-02).
        await self._db.refresh(conversation)
        return conversation
