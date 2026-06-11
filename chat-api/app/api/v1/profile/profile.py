from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import get_current_user

router = APIRouter()


class ProfileResponse(BaseModel):
    sub: str
    email: str | None = None
    name: str | None = None


@router.get("", response_model=ProfileResponse)
async def get_profile(current_user: dict = Depends(get_current_user)) -> ProfileResponse:
    return ProfileResponse(
        sub=current_user["sub"],
        email=current_user.get("email"),
        name=current_user.get("name"),
    )
