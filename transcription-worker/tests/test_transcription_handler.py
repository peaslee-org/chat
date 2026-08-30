"""process_transcription_job — release/abort handling.

The handler imports torch, torchaudio, pyannote and speechbrain at module level and db.py builds
an engine from Settings at import; none of that exists on the host, so tests/conftest.py stubs
the missing roots in sys.modules and this module patches the handler's collaborators.
"""
import json
import threading
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

# torch/pyannote/speechbrain/config/db are stubbed in tests/conftest.py before collection.
import handlers.transcription as handler_mod
from gpu_worker.sqs import Interrupted
from handlers.transcription import process_transcription_job


TRANSCRIPT = {"results": {"items": [
    {"type": "pronunciation", "start_time": "0.0", "end_time": "1.0", "alternatives": [{"content": "hi"}]},
    {"type": "pronunciation", "start_time": "2.0", "end_time": "3.0", "alternatives": [{"content": "there"}]},
]}}
TURNS = [{"start": 0.0, "end": 1.5, "speaker_label": "SPEAKER_00"},
         {"start": 1.5, "end": 3.0, "speaker_label": "SPEAKER_01"}]


def make_job():
    job = MagicMock(status="transcribing", error_message=None, audio_s3_key="audio/a.wav", user_id="u1",
                    speaker_count_hint=None)
    session = MagicMock()
    session.get.return_value = job
    session.execute.return_value.scalars.return_value.all.return_value = []

    @contextmanager
    def get_session():
        yield session
    return job, session, get_session


_last: dict = {}


def run(job_body_extra=None, *, abort=None, poller=None, embedder=None):
    """Drive the handler with every collaborator faked; the job row and session land in `_last`
    so a test can inspect them even when the handler raises."""
    job, session, get_session = make_job()
    _last.update(job=job, session=session)
    poller = poller or MagicMock()
    s3 = MagicMock()
    s3.download_bytes.return_value = json.dumps(TRANSCRIPT).encode()
    embedder = embedder or MagicMock()
    diarizer = MagicMock()
    diarizer.diarize.return_value = {"turns": TURNS}
    settings = MagicMock(DEV_CAPTURE_FIXTURES_S3_PREFIX="", MATCHING_THRESHOLD=0.3, AWS_REGION="us-east-1")
    with patch.object(handler_mod, "get_session", get_session), \
         patch.object(handler_mod, "TranscribePoller", return_value=poller), \
         patch.object(handler_mod, "S3Client", return_value=s3), \
         patch.object(handler_mod.EcapaTdnnEmbedder, "get", return_value=embedder), \
         patch.object(handler_mod.PyannoteDiarizer, "get", return_value=diarizer), \
         patch.object(handler_mod.torchaudio, "load", return_value=(MagicMock(), 16000)):
        process_transcription_job({"job_id": str(uuid.uuid4()), "aws_transcribe_job_name": "aws-1",
                                   **(job_body_extra or {})}, settings, abort=abort)
    return job, session


def events(session):
    return [call.args[0].event for call in session.add.call_args_list
            if getattr(call.args[0], "event", None) is not None]


def test_interrupted_while_polling_puts_the_job_back_to_transcribing_and_reraises():
    """Interrupted is an Exception, so without its own clause it falls into the generic handler
    and the row ends `failed` — for a release that only meant "come back later". The status it
    goes back to must be a real `job_status` value (a MagicMock row accepts anything)."""
    poller = MagicMock()
    poller.wait_for_completion.side_effect = Interrupted("released")
    with pytest.raises(Interrupted):
        run(poller=poller, abort=threading.Event())
    job, session = _last["job"], _last["session"]
    assert job.status == "transcribing"   # the API's pre-worker state, so the redelivery re-runs it
    assert job.status in handler_mod.TranscriptionJob.__table__.c.status.type.enums   # a real job_status
    assert job.error_message is None
    assert "job.failed" not in events(session)


def test_abort_set_mid_embedding_loop_raises_interrupted_before_the_next_turn():
    abort = threading.Event()
    poller = MagicMock()
    poller.wait_for_completion.return_value = {"Transcript": {"TranscriptFileUri": "s3://b/k.json"}}
    poller.parse_words.return_value = []
    embedder = MagicMock()
    embedder.encode_tensor.side_effect = lambda *a, **k: (abort.set(), None)[1]   # release lands after turn 0
    with pytest.raises(Interrupted):
        run(abort=abort, poller=poller, embedder=embedder)
    assert embedder.encode_tensor.call_count == 1      # turn 1 was never embedded


def test_no_abort_event_means_the_loop_runs_every_turn():
    poller = MagicMock()
    poller.wait_for_completion.return_value = {"Transcript": {"TranscriptFileUri": "s3://b/k.json"}}
    poller.parse_words.return_value = []
    embedder = MagicMock()
    embedder.encode_tensor.return_value = None
    job, session = run(poller=poller, embedder=embedder)
    assert embedder.encode_tensor.call_count == len(TURNS)
    assert job.status == "complete"
