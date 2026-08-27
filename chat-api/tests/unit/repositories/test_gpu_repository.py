"""GpuSessionRepository — statement shape verified against a mocked AsyncSession (no real DB)."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from app.repositories.gpu import GpuSessionRepository

NOW = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)
SINCE = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc)


def make_repo(rowcount=None, scalar=0, family="transcription"):
    db = MagicMock()
    result = MagicMock()
    result.rowcount = rowcount
    result.scalar_one = MagicMock(return_value=scalar)
    db.execute = AsyncMock(return_value=result)
    return GpuSessionRepository(db, family=family), db


def compiled(db):
    stmt = db.execute.await_args.args[0]
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


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


async def test_close_open_sessions_is_family_scoped():
    repo, db = make_repo(rowcount=0, family="photogrammetry")
    await repo.close_open_sessions(NOW)
    assert "family = 'photogrammetry'" in compiled(db)


async def test_extend_warm_is_family_scoped():
    repo, db = make_repo(family="transcription")
    await repo.extend_warm(NOW)
    assert "family = 'transcription'" in compiled(db)


async def test_warm_count_is_family_scoped():
    repo, db = make_repo(family="transcription")
    await repo.warm_count_for_user_since("u", SINCE)
    assert "family = 'transcription'" in compiled(db)


async def test_hours_between_sums_all_families_and_ignores_rows_without_instance():
    repo, db = make_repo(scalar=0, family="photogrammetry")
    await repo.hours_between(SINCE, NOW, max_session_seconds=10800)
    sql = compiled(db)
    assert "family" not in sql
    assert "instance_id IS NOT NULL" in sql
    assert "coalesce(gpu_sessions.started_processing_at, gpu_sessions.started_at)" in sql


async def test_sessions_since_is_not_family_scoped():
    repo, db = make_repo(family="photogrammetry")
    db.execute.return_value.scalars.return_value.all.return_value = []
    await repo.sessions_since(SINCE)
    # select(GpuSession) always lists the `family` column; the intent here is no family
    # *predicate* (no "family = ..." filter), not the column's absence from the SELECT list.
    assert "family =" not in compiled(db)


async def test_create_stamps_family():
    repo, db = make_repo(family="photogrammetry")
    db.add = MagicMock()
    db.flush = AsyncMock()
    row = await repo.create(task_arn="arn", started_by="u", reason="job", warm_until=None)
    assert row.family == "photogrammetry"
