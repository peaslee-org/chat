from langsmith import get_current_run_tree, traceable
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.repositories.conversation import ConversationRepository
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.bedrock import get_bedrock_service


def _make_title(text: str, max_len: int = 60) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > max_len // 2:
        truncated = truncated[:last_space]
    return truncated + "…"


class ChatService:
    def __init__(self, db: AsyncSession):
        self._db = db
        self._repo = ConversationRepository(db)
        self._bedrock = get_bedrock_service()

    @traceable(run_type="chain", name="chat-handle")
    async def handle(self, request: ChatRequest, user_sub: str) -> ChatResponse:
        settings = get_settings()
        if request.conversation_id:
            conversation = await self._repo.get(request.conversation_id, user_sub)
        else:
            conversation = await self._repo.create(
                user_sub=user_sub,
                title=_make_title(request.message),
                model_id=request.model_id or settings.bedrock_model_id,
                input_price_per_1k_tokens=request.input_price_per_1k_tokens,
                output_price_per_1k_tokens=request.output_price_per_1k_tokens,
            )

        run = get_current_run_tree()
        if run:
            run.metadata["user_sub"] = user_sub
            run.metadata["conversation_id"] = str(conversation.id)

        history = await self._repo.get_messages(conversation.id)
        messages = [{"role": m.role, "content": m.content} for m in history]
        messages.append({"role": "user", "content": request.message})

        reply = await self._bedrock.invoke(
            messages, model_id=conversation.model_id or settings.bedrock_model_id
        )

        await self._repo.add_message(conversation.id, role="user", content=request.message)
        await self._repo.add_message(conversation.id, role="assistant", content=reply)

        return ChatResponse(conversation_id=conversation.id, reply=reply)
