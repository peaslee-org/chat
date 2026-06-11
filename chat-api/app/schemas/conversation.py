from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ConversationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    title: str | None
    model_id: str | None
    input_price_per_1k_tokens: float | None
    output_price_per_1k_tokens: float | None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    role: str
    content: str
    created_at: datetime
