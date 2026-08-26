"""GpuSessionRepository — statement shape verified against a mocked AsyncSession (no real DB)."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from app.repositories.gpu import GpuSessionRepository

NOW = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)
SINCE = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc)


def make_repo(rowcount=None, scalar=0):
    db = MagicMock()
    result = MagicMock()
    result.rowcount = rowcount
    result.scalar_one = MagicMock(return_value=scalar)
    db.execute = AsyncMock(return_value=result)
    return GpuSessionRepository(db), db


async def test_close_open_sessions_returns_rowcount():
    repo, db = make_repo(rowcount=2)
    n = await repo.close_open_sessions(NOW, end_reason="idle")
    assert n == 2
    stmt = db.execute.await_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "gpu_sessions" in sql
    assert "ended_at IS NULL" in sql
    assert "end_reason='idle'" in sql


async def test_close_open_sessions_defaults_end_reason_unknown():
    repo, db = make_repo(rowcount=0)
    await repo.close_open_sessions(NOW)
    stmt = db.execute.await_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "end_reason='unknown'" in sql


async def test_close_open_sessions_returns_zero_when_rowcount_is_none():
    # Some DBAPI drivers report rowcount as -1/None for statements with no matching rows.
    repo, db = make_repo(rowcount=None)
    assert await repo.close_open_sessions(NOW) == 0


async def test_hours_between_clamps_to_max_session_seconds():
    repo, db = make_repo(scalar=1.5)
    await repo.hours_between(SINCE, NOW, max_session_seconds=10800)
    stmt = db.execute.await_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    # The clamp term: started_at + a 10800s interval, folded into the least(...) with the two
    # existing bounds (coalesce(ended_at, until) and until).
    assert "least(" in sql
    assert "make_interval(secs=>10800" in sql
    assert "greatest(0," in sql  # never lets a clamped span go negative


async def test_hours_between_converts_seconds_to_hours():
    repo, db = make_repo(scalar=5400)  # 1.5h in seconds
    hours = await repo.hours_between(SINCE, NOW, max_session_seconds=10800)
    assert hours == 1.5
