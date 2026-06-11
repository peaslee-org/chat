from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_admin_user

router = APIRouter()


@router.get("")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_admin_user),
) -> dict:
    # TODO: implement user listing (query Cognito ListUsers or a local users table)
    return {"users": []}
