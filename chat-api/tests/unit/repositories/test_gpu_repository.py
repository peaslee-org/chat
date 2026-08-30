"""GpuSessionRepository — statement shape verified against a mocked AsyncSession (no real DB)."""
import uuid
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


async def test_request_release_marks_open_session_of_family_and_clears_warm():
    repo, db = make_repo(rowcount=1, family="photogrammetry")
    n = await repo.request_release(mode="immediate", user_id="admin1", now=NOW)
    assert n == 1
    sql = compiled(db)
    assert "ended_at IS NULL" in sql and "family = 'photogrammetry'" in sql
    assert "release_mode='immediate'" in sql and "release_requested_by='admin1'" in sql
    assert "warm_until=NULL" in sql


# ── startup measurement queries (item C) ──────────────────────────────────────────────────────

async def test_recent_startups_filters_job_sessions_with_a_claim_for_the_family_newest_first():
    repo, db = make_repo(family="photogrammetry")
    db.execute.return_value.scalars.return_value.all.return_value = []
    await repo.recent_startups("photogrammetry", limit=10)
    sql = compiled(db)
    assert "family = 'photogrammetry'" in sql
    assert "reason = 'job'" in sql
    assert "started_processing_at IS NOT NULL" in sql
    assert "ORDER BY gpu_sessions.started_at DESC" in sql
    assert "LIMIT 10" in sql


async def test_open_session_is_the_newest_unended_row_of_the_family():
    repo, db = make_repo(family="photogrammetry")
    db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
    assert await repo.open_session("photogrammetry") is None
    sql = compiled(db)
    assert "ended_at IS NULL" in sql and "family = 'photogrammetry'" in sql
    assert "ORDER BY gpu_sessions.started_at DESC" in sql and "LIMIT 1" in sql


async def test_create_stamps_the_promised_startup_estimate():
    repo, db = make_repo()
    db.add = MagicMock()
    db.flush = AsyncMock()
    row = await repo.create(task_arn="arn", started_by="u", reason="job", warm_until=None,
                            estimated_startup_seconds=400)
    assert row.estimated_startup_seconds == 400


async def test_recent_startups_default_window_is_twenty():
    repo, db = make_repo()
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    await repo.recent_startups("photogrammetry")
    assert "LIMIT 20" in compiled(db)


async def test_record_timings_fills_only_null_columns_of_that_task():
    repo, db = make_repo(rowcount=1)
    t = datetime(2026, 9, 10, 15, 1, tzinfo=timezone.utc)
    await repo.record_timings("arn:task/1", pull_started_at=t, pull_stopped_at=None, container_started_at=t)
    sql = compiled(db)
    assert "gpu_sessions.task_arn = 'arn:task/1'" in sql
    assert "coalesce(gpu_sessions.pull_started_at" in sql
    assert "coalesce(gpu_sessions.container_started_at" in sql
    assert "pull_stopped_at" not in sql


async def test_record_timings_with_nothing_to_set_does_not_hit_the_db():
    repo, db = make_repo()
    await repo.record_timings("arn:task/1", pull_started_at=None)
    db.execute.assert_not_awaited()


async def test_last_ended_session_is_the_most_recently_ended_row_of_the_family():
    repo, db = make_repo(family="photogrammetry")
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    await repo.last_ended_session("photogrammetry")
    sql = compiled(db)
    assert "ended_at IS NOT NULL" in sql
    assert "family = 'photogrammetry'" in sql
    assert "ORDER BY gpu_sessions.ended_at DESC" in sql and "LIMIT 1" in sql


async def test_create_stamps_the_launching_job():
    repo, db = make_repo(family="photogrammetry")
    db.add = MagicMock()
    db.flush = AsyncMock()
    jid = uuid.uuid4()
    row = await repo.create(task_arn="arn", started_by="u", reason="job", warm_until=None, job_id=jid)
    assert row.job_id == jid


async def test_job_labels_looks_each_family_up_in_its_own_jobs_table():
    """Sessions of both families come back from sessions_since (one pool, one budget); a scan's
    label is its name, a transcript's is its created_at (it has no name)."""
    repo, db = make_repo()
    pg, tr = uuid.uuid4(), uuid.uuid4()
    pg_rows = MagicMock(); pg_rows.all.return_value = [(pg, "Sample scan", NOW)]
    tr_rows = MagicMock(); tr_rows.all.return_value = [(tr, SINCE)]
    db.execute = AsyncMock(side_effect=[pg_rows, tr_rows])
    sessions = [MagicMock(family="photogrammetry", job_id=pg), MagicMock(family="transcription", job_id=tr),
                MagicMock(family="transcription", job_id=None)]
    labels = await repo.job_labels(sessions)
    sql = [str(c.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
           for c in db.execute.await_args_list]
    assert "photogrammetry_jobs" in sql[0] and str(pg) in sql[0]
    assert "transcription_jobs" in sql[1] and str(tr) in sql[1]
    assert labels[pg].name == "Sample scan" and labels[pg].created_at == NOW
    assert labels[tr].name is None and labels[tr].created_at == SINCE


async def test_job_labels_with_no_job_sessions_does_not_hit_the_db():
    repo, db = make_repo()
    assert await repo.job_labels([MagicMock(family="transcription", job_id=None)]) == {}
    db.execute.assert_not_awaited()
