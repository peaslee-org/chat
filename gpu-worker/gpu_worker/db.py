"""Session factory + the one table every GPU worker touches (gpu_sessions, by task ARN).

The API owns the schema (chat-api Alembic). This model lists only the columns the
GpuSessionStore reads or writes; extra columns on the real table are ignored.
"""
from contextlib import contextmanager
from datetime import datetime
from typing import Callable, ContextManager, Generator, Optional

from sqlalchemy import DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class GpuSession(Base):
    __tablename__ = "gpu_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_arn: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    instance_id: Mapped[Optional[str]] = mapped_column(String(32))
    started_processing_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    warm_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[Optional[str]] = mapped_column(String(20))
    # Admin release (POST /gpu/release): the worker polls release_mode and exits — after the
    # running job ("graceful") or aborting it ("immediate"). Columns owned by chat-api's migration.
    release_mode: Mapped[Optional[str]] = mapped_column(String(10))
    release_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    release_requested_by: Mapped[Optional[str]] = mapped_column(String(64))


def make_session_factory(database_url: str) -> Callable[[], ContextManager[Session]]:
    """Sync SQLAlchemy sessions from an asyncpg- or psycopg2-style URL (the API's secret is asyncpg)."""
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    engine = create_engine(sync_url, pool_pre_ping=True)
    session_local = sessionmaker(engine, autoflush=False)

    @contextmanager
    def get_session() -> Generator[Session, None, None]:
        with session_local() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    return get_session
