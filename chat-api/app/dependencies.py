from typing import AsyncGenerator, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import verify_cognito_token
import app.db.session as db_session

# auto_error=False so a missing Authorization header doesn't raise 403 automatically;
# allows the dev auth bypass to work without any Authorization header present.
bearer_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with db_session.AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    settings = get_settings()
    if settings.dev_auth_bypass and settings.environment != "prod":
        return {
            "sub": settings.dev_auth_user_sub,
            "cognito:groups": [],
            "email": "dev@localhost",
        }
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    token = credentials.credentials
    payload = await verify_cognito_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return payload


async def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    groups: list[str] = current_user.get("cognito:groups") or []
    if "admin" not in groups:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
