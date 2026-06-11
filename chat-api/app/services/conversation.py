from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.repositories.conversation import ConversationRepository


class ConversationService:
    def __init__(self, db: AsyncSession):
        self._repo = ConversationRepository(db)

    async def list_for_user(self, user_sub: str):
        return await self._repo.list_for_user(user_sub)

    async def delete(self, conversation_id: UUID, user_sub: str):
        conversation = await self._repo.get(conversation_id, user_sub)
        await self._repo.delete(conversation)

    async def get_messages(self, conversation_id: UUID, user_sub: str):
        await self._repo.get(conversation_id, user_sub)
        return await self._repo.get_messages(conversation_id)
