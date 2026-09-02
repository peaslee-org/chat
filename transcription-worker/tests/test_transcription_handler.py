"""process_transcription_job — release/abort handling.

The handler imports torch, torchaudio, pyannote and speechbrain at module level and db.py builds
an engine from Settings at import; none of that exists on the host, so tests/conftest.py stubs
the missing roots in sys.modules and this module patches the handler's collaborators.
"""
import json
import logging
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


def make_job(execute_side_effect=None):
    job = MagicMock(status="transcribing", error_message=None, audio_s3_key="audio/a.wav", user_id="u1",
                    speaker_count_hint=None)
    session = MagicMock()
    session.get.return_value = job
    if execute_side_effect is not None:
        session.execute.side_effect = execute_side_effect
    else:
        session.execute.return_value.scalars.return_value.all.return_value = []

    @contextmanager
    def get_session():
        yield session
    return job, session, get_session


def exec_result(rows):
    """Build one `session.execute(...)` return value whose `.scalars().all()` yields `rows` —
    for stubbing a specific DB query in a `execute_side_effect` sequence."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


_last: dict = {}


def run(job_body_extra=None, *, abort=None, poller=None, embedder=None, execute_side_effect=None, s3=None):
    """Drive the handler with every collaborator faked; the job row and session land in `_last`
    so a test can inspect them even when the handler raises."""
    job, session, get_session = make_job(execute_side_effect)
    poller = poller or MagicMock()
    if s3 is None:
        s3 = MagicMock()
        s3.download_bytes.return_value = json.dumps(TRANSCRIPT).encode()
    embedder = embedder or MagicMock()
    _last.update(job=job, session=session, s3=s3, embedder=embedder)
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


def test_processing_sample_for_filtered_speaker_is_embedded_inline_and_joins_candidates(caplog):
    """The sample flow race (live prod, 2026-09-02): a `sample_embedding` message for a speaker
    named in the job's `speaker_ids` can still be queued behind the job message, so the sample is
    `processing` when candidate loading runs. The candidate query alone would then see it, so the
    handler must embed it inline (the ECAPA model is already loaded) before matching."""
    speaker_id = uuid.uuid4()
    pending = MagicMock(id=uuid.uuid4(), speaker_profile_id=speaker_id, s3_key="samples/pending.wav",
                         status="processing", embedding=None)
    profile = MagicMock(id=speaker_id, speaker_name="Alice")

    poller = MagicMock()
    poller.wait_for_completion.return_value = {"Transcript": {"TranscriptFileUri": "s3://b/k.json"}}
    poller.parse_words.return_value = []
    embedder = MagicMock()
    embedder.encode_tensor.return_value = None          # turn matching itself is out of scope here
    embedder.encode.return_value = [0.1] * 192

    with caplog.at_level(logging.INFO, logger=handler_mod.__name__):
        job, session = run(
            job_body_extra={"speaker_ids": [str(speaker_id)]},
            poller=poller,
            embedder=embedder,
            execute_side_effect=[
                exec_result([]),          # step 7: no `ready` samples yet
                exec_result([pending]),   # this fix: `processing` samples of the filtered speakers
                exec_result([profile]),   # speaker-profile name lookup
            ],
        )

    s3 = _last["s3"]
    s3.download_bytes.assert_any_call(pending.s3_key)
    embedder.encode.assert_called_once_with(s3.download_bytes.return_value)
    assert pending.status == "ready"
    assert pending.embedding == [0.1] * 192
    assert "Loaded 1 candidate sample(s)" in caplog.text
    assert job.status == "complete"


def test_one_failing_inline_embed_is_contained_and_the_other_sample_still_joins_candidates(caplog):
    """A raced sample's inline embed can itself fail (bad S3 key, corrupt audio, model error).
    That must only fail the one sample — not the whole job — matching the dedicated embedding
    handler's per-sample containment (handlers/embedding.py)."""
    speaker_fail = uuid.uuid4()
    speaker_ok = uuid.uuid4()
    pending_fail = MagicMock(id=uuid.uuid4(), speaker_profile_id=speaker_fail, s3_key="samples/fail.wav",
                              status="processing", embedding=None, error_message=None)
    pending_ok = MagicMock(id=uuid.uuid4(), speaker_profile_id=speaker_ok, s3_key="samples/ok.wav",
                            status="processing", embedding=None, error_message=None)
    profile = MagicMock(id=speaker_ok, speaker_name="Bob")

    poller = MagicMock()
    poller.wait_for_completion.return_value = {"Transcript": {"TranscriptFileUri": "s3://b/k.json"}}
    poller.parse_words.return_value = []
    embedder = MagicMock()
    embedder.encode_tensor.return_value = None
    embedder.encode.side_effect = lambda audio_bytes: (
        (_ for _ in ()).throw(RuntimeError("model blew up")) if audio_bytes == b"fail-bytes"
        else [0.2] * 192
    )

    def download_side_effect(key):
        if key == "k.json":
            return json.dumps(TRANSCRIPT).encode()
        if key == pending_fail.s3_key:
            return b"fail-bytes"
        if key == pending_ok.s3_key:
            return b"ok-bytes"
        return b""

    s3 = MagicMock()
    s3.download_bytes.side_effect = download_side_effect

    with caplog.at_level(logging.ERROR, logger=handler_mod.__name__):
        job, session = run(
            job_body_extra={"speaker_ids": [str(speaker_fail), str(speaker_ok)]},
            poller=poller,
            embedder=embedder,
            s3=s3,
            execute_side_effect=[
                exec_result([]),                          # step 7: no `ready` samples yet
                exec_result([pending_fail, pending_ok]),   # `processing` samples of filtered speakers
                exec_result([profile]),                    # speaker-profile name lookup
            ],
        )

    assert pending_fail.status == "failed"
    assert pending_fail.error_message == "model blew up"
    assert pending_ok.status == "ready"
    assert pending_ok.embedding == [0.2] * 192
    assert job.status == "complete"


def test_no_speaker_ids_filter_skips_the_processing_lookup():
    """No `speaker_ids` means "match against every ready sample" — there is no "filtered
    speakers" set for the race fix to act on, so the extra processing-sample query must not run."""
    poller = MagicMock()
    poller.wait_for_completion.return_value = {"Transcript": {"TranscriptFileUri": "s3://b/k.json"}}
    poller.parse_words.return_value = []
    embedder = MagicMock()
    embedder.encode_tensor.return_value = None

    run(
        poller=poller,
        embedder=embedder,
        execute_side_effect=[
            exec_result([]),   # step 7: no `ready` samples
            exec_result([]),   # speaker-profile name lookup (empty since no samples)
        ],
    )
    embedder.encode.assert_not_called()
