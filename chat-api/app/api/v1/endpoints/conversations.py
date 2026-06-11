from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_current_user
from app.schemas.conversation import ConversationOut, MessageOut
from app.services.conversation import ConversationService

router = APIRouter()


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    service = ConversationService(db)
    return await service.list_for_user(user_sub=current_user["sub"])


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    service = ConversationService(db)
    return await service.get_messages(conversation_id, user_sub=current_user["sub"])


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    service = ConversationService(db)
    await service.delete(conversation_id, user_sub=current_user["sub"])
