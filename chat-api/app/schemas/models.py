from pydantic import BaseModel


class ModelOut(BaseModel):
    model_id: str
    model_name: str
    provider_name: str
    input_price_per_1k_tokens: float | None = None
    output_price_per_1k_tokens: float | None = None
