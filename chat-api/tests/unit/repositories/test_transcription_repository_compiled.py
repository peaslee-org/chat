"""upsert_compiled_transcript must be an atomic Postgres upsert (ON CONFLICT DO UPDATE), not a
read-then-write — two concurrent first reads racing to insert would otherwise 500 on the unique
index on job_id. Statement shape verified against a mocked AsyncSession, no database required."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.repositories.transcription import TranscriptionRepository


def make_repo():
    db = MagicMock()
    result = MagicMock()
    result.scalar_one = MagicMock(return_value=MagicMock())
    db.execute = AsyncMock(return_value=result)
    return TranscriptionRepository(db), db


def compiled_sql(db) -> str:
    stmt = db.execute.await_args.args[0]
    return str(stmt.compile(dialect=postgresql.dialect()))


async def test_upsert_compiled_transcript_is_an_atomic_upsert():
    repo, db = make_repo()
    job_id = uuid4()
    settings = {"cosine_dist_threshold": 0.25, "separation_min": 0.0, "quality_min": 0.0, "confidence_min": 0.0}
    turns = [{"start_time": 0.0, "end_time": 1.0, "text": "hi", "label": "Jane", "match_type": "high"}]
    compiled_at = datetime.now(timezone.utc)

    await repo.upsert_compiled_transcript(job_id=job_id, settings=settings, turns=turns, compiled_at=compiled_at)

    sql = compiled_sql(db)
    assert "ON CONFLICT (job_id) DO UPDATE" in sql
    assert "RETURNING" in sql
    db.execute.assert_awaited_once()
