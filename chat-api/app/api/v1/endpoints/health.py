from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_db

router = APIRouter()


@router.get("")
async def health():
    """Liveness probe."""
    settings = get_settings()
    return {"status": "ok", "mock_bedrock": settings.use_mock_bedrock}


@router.get("/ready")
async def ready(db: AsyncSession = Depends(get_db)):
    """Readiness probe — verifies DB connectivity."""
    await db.execute(text("SELECT 1"))
    return {"status": "ready"}
