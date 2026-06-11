"""Unit tests for sample upload validation in TranscriptionService."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AudioValidationError
from app.services.transcription_service import TranscriptionService


def make_service_with_sample(duration_ms: int | None = None, raise_decode: bool = False):
    speaker_id = uuid4()
    sample_id = uuid4()

    repo = MagicMock()
    fake_speaker = MagicMock()
    fake_speaker.id = speaker_id
    repo.get_speaker = AsyncMock(return_value=fake_speaker)

    fake_sample = MagicMock()
    fake_sample.id = sample_id
    fake_sample.s3_key = f"audio/user/speakers/{speaker_id}/samples/{sample_id}"
    fake_sample.created_at = MagicMock()
    repo.get_sample = AsyncMock(return_value=fake_sample)
    repo.update_sample_status = AsyncMock()
    repo.db = MagicMock()
    repo.db.commit = AsyncMock()

    storage = MagicMock()
    storage.get_object_bytes = MagicMock(return_value=b"fake audio bytes")

    sqs = MagicMock()
    sqs.publish_sample_embedding = MagicMock()

    settings = MagicMock()

    if raise_decode:
        pydub_mock = MagicMock(side_effect=Exception("CouldntDecodeError"))
    elif duration_ms is not None:
        audio_mock = MagicMock()
        audio_mock.__len__ = MagicMock(return_value=duration_ms)
        pydub_mock = MagicMock(return_value=audio_mock)
    else:
        pydub_mock = MagicMock()

    service = TranscriptionService(repo, storage, sqs, settings)
    return service, repo, sqs, speaker_id, sample_id, pydub_mock


class TestConfirmSampleUpload:
    async def test_422_duration_too_short(self):
        service, repo, _, speaker_id, sample_id, pydub_mock = make_service_with_sample(
            duration_ms=5_000  # 5 seconds — below 10s minimum
        )
        from pydub import AudioSegment
        with patch.object(AudioSegment, "from_file", pydub_mock):
            with pytest.raises(AudioValidationError) as exc_info:
                await service.confirm_sample_upload("user1", speaker_id, sample_id)
        assert exc_info.value.error_code == "duration_too_short"
        repo.update_sample_status.assert_called_with(sample_id, "failed")

    async def test_422_duration_too_long(self):
        service, repo, _, speaker_id, sample_id, pydub_mock = make_service_with_sample(
            duration_ms=90_000  # 90 seconds — above 60s maximum
        )
        from pydub import AudioSegment
        with patch.object(AudioSegment, "from_file", pydub_mock):
            with pytest.raises(AudioValidationError) as exc_info:
                await service.confirm_sample_upload("user1", speaker_id, sample_id)
        assert exc_info.value.error_code == "duration_too_long"
        repo.update_sample_status.assert_called_with(sample_id, "failed")

    async def test_422_unsupported_format(self):
        service, repo, _, speaker_id, sample_id, _ = make_service_with_sample()
        from pydub import AudioSegment
        from pydub.exceptions import CouldntDecodeError
        with patch.object(AudioSegment, "from_file", side_effect=CouldntDecodeError):
            with pytest.raises(AudioValidationError) as exc_info:
                await service.confirm_sample_upload("user1", speaker_id, sample_id)
        assert exc_info.value.error_code == "unsupported_format"
        repo.update_sample_status.assert_called_with(sample_id, "failed")

    async def test_valid_sample_publishes_embedding(self):
        service, repo, sqs, speaker_id, sample_id, pydub_mock = make_service_with_sample(
            duration_ms=30_000  # 30 seconds — valid
        )
        from pydub import AudioSegment
        with patch.object(AudioSegment, "from_file", pydub_mock):
            result = await service.confirm_sample_upload("user1", speaker_id, sample_id)

        sqs.publish_sample_embedding.assert_called_once_with(
            sample_id,
            f"audio/user/speakers/{speaker_id}/samples/{sample_id}",
        )
        repo.update_sample_status.assert_called_once_with(
            sample_id, "processing", duration_seconds=30.0
        )
        assert result.status == "processing"
