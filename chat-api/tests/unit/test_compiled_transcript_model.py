from app.models.transcription import CompiledTranscript


def test_compiled_transcript_table_shape():
    t = CompiledTranscript.__table__
    assert t.name == "compiled_transcripts"
    assert t.c.job_id.unique is True
    fk = next(iter(t.c.job_id.foreign_keys))
    assert fk.column.table.name == "transcription_jobs" and fk.ondelete == "CASCADE"
    assert t.c.settings.nullable is False
    assert t.c.turns.nullable is False
    assert t.c.compiled_at.nullable is False
