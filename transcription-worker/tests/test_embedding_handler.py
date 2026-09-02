"""process_sample_embedding — no-op guard for an already-`ready` sample.

Companion to the transcription handler's inline embed-ahead-of-matching race fix
(test_transcription_handler.py): once that fix embeds a `processing` sample inline and flips it
to `ready`, the sample's own queued `sample_embedding` message is still delivered later and must
land as a harmless no-op rather than re-downloading audio and re-embedding.

db/config/torch/speechbrain are stubbed the same way as test_transcription_handler.py (see
tests/conftest.py); collaborators are patched directly on the handler module.
"""
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import handlers.embedding as handler_mod
from handlers.embedding import process_sample_embedding


def _get_session_for(sample):
    session = MagicMock()
    session.get.return_value = sample

    @contextmanager
    def get_session():
        yield session
    return session, get_session


def test_already_ready_sample_is_a_harmless_noop():
    sample = MagicMock(id=uuid.uuid4(), status="ready", embedding=[0.1] * 192, error_message=None)
    session, get_session = _get_session_for(sample)
    s3 = MagicMock()
    embedder = MagicMock()

    with patch.object(handler_mod, "get_session", get_session), \
         patch.object(handler_mod, "S3Client", return_value=s3), \
         patch.object(handler_mod.EcapaTdnnEmbedder, "get", return_value=embedder):
        process_sample_embedding({"sample_id": str(sample.id), "s3_key": "samples/x.wav"}, MagicMock())

    s3.download_bytes.assert_not_called()
    embedder.encode.assert_not_called()
    assert sample.status == "ready"
    assert sample.embedding == [0.1] * 192


def test_processing_sample_is_still_embedded_and_marked_ready():
    """Baseline (unchanged) behavior: a sample still `processing` — the normal, non-raced case —
    gets its audio downloaded, embedded, and flipped to `ready`."""
    sample = MagicMock(id=uuid.uuid4(), status="processing", embedding=None, error_message=None)
    session, get_session = _get_session_for(sample)
    s3 = MagicMock()
    s3.download_bytes.return_value = b"wav-bytes"
    embedder = MagicMock()
    embedder.encode.return_value = [0.2] * 192

    with patch.object(handler_mod, "get_session", get_session), \
         patch.object(handler_mod, "S3Client", return_value=s3), \
         patch.object(handler_mod.EcapaTdnnEmbedder, "get", return_value=embedder):
        process_sample_embedding({"sample_id": str(sample.id), "s3_key": "samples/x.wav"}, MagicMock())

    s3.download_bytes.assert_called_once_with("samples/x.wav")
    embedder.encode.assert_called_once_with(b"wav-bytes")
    assert sample.status == "ready"
    assert sample.embedding == [0.2] * 192
