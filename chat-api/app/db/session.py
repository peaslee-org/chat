from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine = None
AsyncSessionLocal: async_sessionmaker[AsyncSession] = None  # type: ignore


async def init_db() -> None:
    global _engine, AsyncSessionLocal
    settings = get_settings()
    _engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    AsyncSessionLocal = async_sessionmaker(_engine, expire_on_commit=False)
