from uuid import UUID

from pydantic import BaseModel


class ChatRequest(BaseModel):
    conversation_id: UUID | None = None
    message: str
    model_id: str | None = None
    input_price_per_1k_tokens: float | None = None
    output_price_per_1k_tokens: float | None = None


class ChatResponse(BaseModel):
    conversation_id: UUID
    reply: str
