"""Unit tests for TranscriptionService — no real DB, S3, or SQS."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ConcurrentJobLimitExceeded, ConflictError, NotFoundError
from app.schemas.transcription import JobCreateRequest
from app.services.transcription_service import TranscriptionService


def make_service(
    *,
    active_jobs: int = 0,
    max_concurrent_jobs: int = 3,
    gpu=None,
):
    repo = MagicMock()
    repo.count_active_jobs = AsyncMock(return_value=active_jobs)
    repo.create_job = AsyncMock()
    repo.get_job = AsyncMock(return_value=None)
    repo.update_job_status = AsyncMock()
    repo.list_jobs = AsyncMock(return_value=([], None))
    repo.delete_job = AsyncMock()
    repo.get_segments = AsyncMock(return_value=[])
    repo.create_speaker = AsyncMock()
    repo.get_speaker = AsyncMock(return_value=None)
    repo.list_speakers = AsyncMock(return_value=([], None))
    repo.delete_speaker = AsyncMock()
    repo.create_sample = AsyncMock()
    repo.get_sample = AsyncMock(return_value=None)
    repo.update_sample_status = AsyncMock()
    repo.delete_sample = AsyncMock()
    repo.append_event = AsyncMock()
    repo.get_speakers_without_ready_samples = AsyncMock(return_value=[])
    repo.db = MagicMock()
    repo.db.commit = AsyncMock()

    storage = MagicMock()
    storage.generate_presigned_upload_url = MagicMock(return_value="https://s3.example.com/upload")
    storage.object_exists = MagicMock(return_value=True)
    storage.start_transcription_job = MagicMock(return_value=("job-abc", "audio/user/job/transcript_raw.json"))
    storage.delete_objects = MagicMock()
    storage.list_keys_with_prefix = MagicMock(return_value=[])

    sqs = MagicMock()
    sqs.publish_transcription_job = MagicMock()
    sqs.publish_sample_embedding = MagicMock()

    settings = MagicMock()
    settings.max_concurrent_jobs = max_concurrent_jobs

    return TranscriptionService(repo, storage, sqs, settings, gpu), repo, storage, sqs


class TestInitiateJobUpload:
    async def test_raises_429_when_at_limit(self):
        service, *_ = make_service(active_jobs=3, max_concurrent_jobs=3)
        with pytest.raises(ConcurrentJobLimitExceeded):
            await service.initiate_job_upload("user1", JobCreateRequest())

    async def test_creates_job_and_returns_upload_url(self):
        service, repo, storage, _ = make_service(active_jobs=0)
        fake_job = MagicMock()
        fake_job.id = uuid4()
        repo.create_job.return_value = fake_job

        result = await service.initiate_job_upload("user1", JobCreateRequest())

        repo.create_job.assert_called_once()
        storage.generate_presigned_upload_url.assert_called_once()
        assert result.upload_url == "https://s3.example.com/upload"
        assert result.job_id == fake_job.id

    async def test_s3_key_includes_user_and_job_id(self):
        service, repo, storage, _ = make_service(active_jobs=0)
        fake_job = MagicMock()
        fake_job.id = uuid4()
        repo.create_job.return_value = fake_job

        await service.initiate_job_upload("user42", JobCreateRequest())

        call_kwargs = repo.create_job.call_args
        s3_key = call_kwargs.kwargs.get("audio_s3_key") or call_kwargs.args[1]
        assert "user42" in s3_key


class TestConfirmJobUpload:
    async def test_404_when_job_not_found(self):
        service, repo, *_ = make_service()
        repo.get_job.return_value = None
        with pytest.raises(NotFoundError):
            await service.confirm_job_upload("user1", uuid4())

    async def test_409_when_job_not_pending(self):
        service, repo, *_ = make_service()
        fake_job = MagicMock()
        fake_job.status = "transcribing"
        repo.get_job.return_value = fake_job
        with pytest.raises(ConflictError):
            await service.confirm_job_upload("user1", fake_job.id)

    async def test_422_when_file_missing(self):
        from app.core.exceptions import AudioUploadMissing
        service, repo, storage, _ = make_service()
        fake_job = MagicMock()
        fake_job.status = "pending"
        fake_job.audio_s3_key = "some/key"
        fake_job.speaker_count_hint = None
        fake_job.language = "en-US"
        repo.get_job.return_value = fake_job
        storage.object_exists.return_value = False
        with pytest.raises(AudioUploadMissing):
            await service.confirm_job_upload("user1", fake_job.id)

    async def test_successful_confirm_starts_transcription(self):
        service, repo, storage, sqs = make_service()
        job_id = uuid4()
        fake_job = MagicMock()
        fake_job.id = job_id
        fake_job.status = "pending"
        fake_job.audio_s3_key = "audio/user/job/source"
        fake_job.speaker_count_hint = None
        fake_job.language = "en-US"
        repo.get_job.return_value = fake_job

        await service.confirm_job_upload("user1", job_id)

        storage.start_transcription_job.assert_called_once()
        sqs.publish_transcription_job.assert_called_once()
        repo.update_job_status.assert_called_once_with(
            job_id,
            "transcribing",
            aws_transcribe_job_name="job-abc",
            transcribe_output_s3_key="audio/user/job/transcript_raw.json",
        )

    async def test_confirm_passes_speaker_hint_to_storage(self):
        service, repo, storage, _ = make_service()
        job_id = uuid4()
        fake_job = MagicMock()
        fake_job.id = job_id
        fake_job.status = "pending"
        fake_job.audio_s3_key = "audio/user/job/source"
        fake_job.speaker_count_hint = 3
        fake_job.language = "en-US"
        repo.get_job.return_value = fake_job

        await service.confirm_job_upload("user1", job_id)

        call_kwargs = storage.start_transcription_job.call_args.kwargs
        assert call_kwargs.get("speaker_count_hint") == 3


class TestConfirmJobUploadSpeakerCheck:
    def _pending_job(self, speaker_ids=None):
        fake_job = MagicMock()
        fake_job.status = "pending"
        fake_job.audio_s3_key = "audio/user/job/source"
        fake_job.speaker_count_hint = None
        fake_job.language = "en-US"
        fake_job.speaker_ids = [str(s) for s in (speaker_ids or [])]
        return fake_job

    async def test_409_when_speaker_sample_not_ready(self):
        service, repo, storage, sqs = make_service()
        speaker_id = uuid4()
        fake_job = self._pending_job(speaker_ids=[speaker_id])
        repo.get_job.return_value = fake_job
        repo.get_speakers_without_ready_samples.return_value = [speaker_id]

        with pytest.raises(ConflictError):
            await service.confirm_job_upload("user1", fake_job.id, speaker_ids=[speaker_id])

        sqs.publish_transcription_job.assert_not_called()
        storage.start_transcription_job.assert_not_called()

    async def test_409_uses_job_speaker_ids_when_none_passed(self):
        service, repo, storage, sqs = make_service()
        speaker_id = uuid4()
        fake_job = self._pending_job(speaker_ids=[speaker_id])
        repo.get_job.return_value = fake_job
        repo.get_speakers_without_ready_samples.return_value = [speaker_id]

        with pytest.raises(ConflictError):
            await service.confirm_job_upload("user1", fake_job.id, speaker_ids=None)

        sqs.publish_transcription_job.assert_not_called()

    async def test_no_check_when_no_speaker_ids(self):
        service, repo, storage, sqs = make_service()
        fake_job = self._pending_job()
        repo.get_job.return_value = fake_job

        await service.confirm_job_upload("user1", fake_job.id, speaker_ids=[])

        repo.get_speakers_without_ready_samples.assert_not_called()
        sqs.publish_transcription_job.assert_called_once()

    async def test_proceeds_when_all_samples_ready(self):
        service, repo, storage, sqs = make_service()
        speaker_id = uuid4()
        fake_job = self._pending_job(speaker_ids=[speaker_id])
        repo.get_job.return_value = fake_job
        repo.get_speakers_without_ready_samples.return_value = []  # all ready

        await service.confirm_job_upload("user1", fake_job.id, speaker_ids=[speaker_id])

        sqs.publish_transcription_job.assert_called_once()


class TestGetTranscript:
    async def test_409_when_still_processing(self):
        service, repo, *_ = make_service()
        for status in ("pending", "transcribing", "matching"):
            fake_job = MagicMock()
            fake_job.status = status
            repo.get_job.return_value = fake_job
            with pytest.raises(ConflictError):
                await service.get_transcript("user1", uuid4())

    async def test_returns_segments_on_complete(self):
        service, repo, storage, _ = make_service()
        fake_job = MagicMock()
        fake_job.status = "complete"
        repo.get_job.return_value = fake_job

        seg = MagicMock()
        seg.id = uuid4()
        seg.anonymous_label = "spk_0"
        seg.speaker_profile = None
        seg.start_time = 0.0
        seg.end_time = 5.0
        seg.text = "Hello world"
        repo.get_segments.return_value = [seg]

        result = await service.get_transcript("user1", fake_job.id)

        assert len(result.segments) == 1

    async def test_partial_transcript_on_failed_with_output(self):
        service, repo, *_ = make_service()
        fake_job = MagicMock()
        fake_job.status = "failed"
        fake_job.transcribe_output_s3_key = "some/key"
        repo.get_job.return_value = fake_job
        repo.get_segments.return_value = []

        result = await service.get_transcript("user1", fake_job.id)

        assert len(result.segments) == 0

    async def test_409_on_failed_without_partial_data(self):
        service, repo, *_ = make_service()
        fake_job = MagicMock()
        fake_job.status = "failed"
        fake_job.transcribe_output_s3_key = None
        repo.get_job.return_value = fake_job

        with pytest.raises(ConflictError):
            await service.get_transcript("user1", fake_job.id)


class TestDeleteJob:
    async def test_404_when_not_found(self):
        service, repo, *_ = make_service()
        repo.get_job.return_value = None
        with pytest.raises(NotFoundError):
            await service.delete_job("user1", uuid4())

    async def test_deletes_s3_keys_and_job(self):
        service, repo, storage, _ = make_service()
        fake_job = MagicMock()
        fake_job.audio_s3_key = "audio/user/job/source"
        fake_job.transcribe_output_s3_key = "audio/user/job/raw.json"
        repo.get_job.return_value = fake_job

        job_id = uuid4()
        await service.delete_job("user1", job_id)

        storage.delete_objects.assert_called_once()
        deleted_keys = storage.delete_objects.call_args.args[0]
        assert "audio/user/job/source" in deleted_keys
        repo.delete_job.assert_called_once_with(job_id)


class TestGetJobStatus:
    async def test_matched_counts_included_in_response(self):
        """Regression: matched_speaker_count and total_segment_count must be forwarded."""
        service, repo, *_ = make_service()
        fake_job = MagicMock()
        fake_job.id = uuid4()
        fake_job.status = "complete"
        fake_job.speaker_count_hint = None
        fake_job.language = "en-US"
        fake_job.speaker_ids = []
        fake_job.error_message = None
        fake_job.transcribe_output_s3_key = None
        fake_job.matched_speaker_count = 4
        fake_job.total_segment_count = 6
        fake_job.created_at = MagicMock()
        fake_job.updated_at = MagicMock()
        fake_job.completed_at = MagicMock()
        repo.get_job.return_value = fake_job

        result = await service.get_job_status("user1", fake_job.id)

        assert result.matched_speaker_count == 4
        assert result.total_segment_count == 6

    async def test_matched_counts_none_when_not_set(self):
        service, repo, *_ = make_service()
        fake_job = MagicMock()
        fake_job.id = uuid4()
        fake_job.status = "matching"
        fake_job.speaker_count_hint = None
        fake_job.language = "en-US"
        fake_job.speaker_ids = []
        fake_job.error_message = None
        fake_job.transcribe_output_s3_key = None
        fake_job.matched_speaker_count = None
        fake_job.total_segment_count = None
        fake_job.created_at = MagicMock()
        fake_job.updated_at = MagicMock()
        fake_job.completed_at = None
        repo.get_job.return_value = fake_job

        result = await service.get_job_status("user1", fake_job.id)

        assert result.matched_speaker_count is None
        assert result.total_segment_count is None


class TestGetTranscriptSpeakerName:
    async def test_speaker_name_populated_from_matched_profile(self):
        """Regression: speaker_name must come from the eagerly-loaded speaker_profile."""
        service, repo, storage, _ = make_service()
        fake_job = MagicMock()
        fake_job.status = "complete"

        repo.get_job.return_value = fake_job

        fake_profile = MagicMock()
        fake_profile.speaker_name = "Barry"

        seg = MagicMock()
        seg.id = uuid4()
        seg.anonymous_label = "spk_0"
        seg.speaker_profile = fake_profile
        seg.start_time = 0.0
        seg.end_time = 15.0
        seg.text = "Hello world"
        repo.get_segments.return_value = [seg]

        result = await service.get_transcript("user1", fake_job.id)

        assert result.segments[0].speaker_name == "Barry"

    async def test_speaker_name_none_when_unmatched(self):
        service, repo, storage, _ = make_service()
        fake_job = MagicMock()
        fake_job.status = "complete"

        repo.get_job.return_value = fake_job

        seg = MagicMock()
        seg.id = uuid4()
        seg.anonymous_label = "spk_1"
        seg.speaker_profile = None
        seg.start_time = 15.0
        seg.end_time = 22.0
        seg.text = "Goodbye"
        repo.get_segments.return_value = [seg]

        result = await service.get_transcript("user1", fake_job.id)

        assert result.segments[0].speaker_name is None


class TestGpuIntegration:
    async def test_confirm_calls_ensure_worker_and_records_cap(self):
        from app.services.gpu_controller import GpuCapExceeded

        gpu = MagicMock()
        gpu.ensure_worker = AsyncMock(
            side_effect=GpuCapExceeded("Daily GPU budget used (3 h). Resets at midnight UTC.")
        )
        service, repo, storage, sqs = make_service(gpu=gpu)
        job_id = uuid4()
        fake_job = MagicMock()
        fake_job.id = job_id
        fake_job.status = "pending"
        fake_job.audio_s3_key = "audio/user/job/source"
        fake_job.speaker_count_hint = None
        fake_job.language = "en-US"
        repo.get_job.return_value = fake_job

        await service.confirm_job_upload("user1", job_id)

        gpu.ensure_worker.assert_awaited_once_with("job", "user1", job_id=job_id)
        repo.append_event.assert_any_await(
            job_id,
            "api",
            "gpu.capped",
            {"reason": "Daily GPU budget used (3 h). Resets at midnight UTC."},
        )

    async def test_status_resumes_worker_when_off_and_job_active(self):
        from app.schemas.gpu import GpuStateResponse

        gpu = MagicMock()
        gpu.get_state = AsyncMock(
            return_value=GpuStateResponse(worker_state="off", estimated_wait_seconds=180)
        )
        gpu.ensure_worker = AsyncMock(
            return_value=GpuStateResponse(worker_state="starting", estimated_wait_seconds=120)
        )
        service, repo, _, _ = make_service(gpu=gpu)
        job_id = uuid4()
        fake_job = MagicMock()
        fake_job.id = job_id
        fake_job.status = "transcribing"
        fake_job.speaker_count_hint = None
        fake_job.language = "en-US"
        fake_job.speaker_ids = []
        fake_job.error_message = None
        fake_job.transcribe_output_s3_key = None
        fake_job.matched_speaker_count = None
        fake_job.total_segment_count = None
        fake_job.created_at = MagicMock()
        fake_job.updated_at = MagicMock()
        fake_job.completed_at = None
        repo.get_job = AsyncMock(return_value=fake_job)

        resp = await service.get_job_status("user1", job_id)

        gpu.ensure_worker.assert_awaited_once_with("resume", "user1")
        assert resp.worker_state == "starting"
        assert resp.estimated_wait_seconds == 120
