"""gpu_sessions.family: column with a server default, and the summary schema carries it."""
from sqlalchemy import inspect

from app.models.gpu import GpuSession
from app.schemas.gpu import GpuFamily, GpuSessionSummary


def test_family_column_defaults_to_transcription():
    col = inspect(GpuSession).columns["family"]
    assert col.type.length == 32 and col.nullable is False
    assert col.server_default.arg == "transcription"


def test_summary_carries_family():
    s = GpuSessionSummary(started_at="2026-09-10T15:00:00Z", ended_at=None, reason="job",
                          started_by="u", end_reason=None, hours=0.5, family="photogrammetry")
    assert s.family == "photogrammetry"


def test_family_literal():
    assert set(GpuFamily.__args__) == {"transcription", "photogrammetry"}
