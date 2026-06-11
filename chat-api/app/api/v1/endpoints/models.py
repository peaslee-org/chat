from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.schemas.models import ModelOut
from app.services.bedrock import get_bedrock_service

router = APIRouter()


@router.get("", response_model=list[ModelOut])
async def list_models(
    current_user: dict = Depends(get_current_user),
):
    service = get_bedrock_service()
    return await service.list_models()
