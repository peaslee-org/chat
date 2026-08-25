"""GpuSessionStore never raises; it updates the row RunTask created (matched by task ARN)."""
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/x")
os.environ.setdefault("AUDIO_BUCKET_NAME", "b")
os.environ.setdefault("TRANSCRIBE_SQS_QUEUE_URL", "https://sqs.test/q")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.gpu_session import GpuSessionStore  # noqa: E402


def make_store(row=None, raise_on_enter=False):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.one_or_none.return_value = row

    @contextmanager
    def factory():
        if raise_on_enter:
            raise RuntimeError("db down")
        yield session

    return GpuSessionStore("arn:aws:ecs:r:a:task/c/1", "i-123", session_factory=factory), session


def test_claim_fills_instance_and_processing_time():
    row = MagicMock(instance_id=None, started_processing_at=None)
    store, _ = make_store(row)
    store.claim()
    assert row.instance_id == "i-123"
    assert isinstance(row.started_processing_at, datetime)


def test_warm_until_returns_row_value():
    until = datetime(2026, 9, 1, tzinfo=timezone.utc)
    store, _ = make_store(MagicMock(warm_until=until))
    assert store.warm_until() == until


def test_missing_row_is_tolerated():
    store, _ = make_store(row=None)
    store.claim()
    store.heartbeat()
    assert store.warm_until() is None
    store.close("idle")


def test_db_errors_are_swallowed():
    store, _ = make_store(raise_on_enter=True)
    store.claim()
    store.heartbeat()
    assert store.warm_until() is None
    store.close("idle")


def test_no_task_arn_is_a_noop():
    store = GpuSessionStore(None, None, session_factory=MagicMock())
    store.claim()
    assert store.warm_until() is None
