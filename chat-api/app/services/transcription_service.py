import asyncio
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

from app.core.exceptions import (
    AudioUploadMissing,
    AudioValidationError,
    ConcurrentJobLimitExceeded,
    ConflictError,
    NotFoundError,
)
from app.repositories.transcription import TranscriptionRepository
from app.schemas.transcription import (
    AudioUrlResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobEventResponse,
    JobListResponse,
    JobStatusResponse,
    SampleAudioItem,
    SampleJobResponse,
    SamplePreviewResponse,
    SampleResponse,
    SampleSpeakerItem,
    SampleUploadInitResponse,
    SegmentResponse,
    SpeakerListResponse,
    SpeakerResponse,
    TranscriptResponse,
    TurnCandidateResponse,
    TurnDistanceResponse,
    TurnDistancesResponse,
)
from app.services.audio_storage import AudioStorageService
from app.services.gpu_controller import GpuCapExceeded
from app.services.sqs_publisher import SQSPublisher

DOWNLOAD_TTL_SECONDS = 900


class TranscriptionService:

    def __init__(
        self,
        repo: TranscriptionRepository,
        storage: AudioStorageService,
        sqs: SQSPublisher,
        settings,
        gpu=None,
    ):
        self._repo = repo
        self._storage = storage
        self._sqs = sqs
        self._settings = settings
        self._gpu = gpu

    # ── Speaker Profiles ──────────────────────────────────────────────────────

    async def create_speaker(self, user_id: str, speaker_name: str) -> SpeakerResponse:
        speaker = await self._repo.create_speaker(user_id, speaker_name)
        return SpeakerResponse(
            speaker_id=speaker.id,
            speaker_name=speaker.speaker_name,
            created_at=speaker.created_at,
        )

    async def list_speakers(
        self, user_id: str, cursor: Optional[str], limit: int
    ) -> SpeakerListResponse:
        items, next_cursor = await self._repo.list_speakers(user_id, cursor, limit)
        return SpeakerListResponse(
            items=[
                SpeakerResponse(
                    speaker_id=s.id,
                    speaker_name=s.speaker_name,
                    created_at=s.created_at,
                    samples=[
                        SampleResponse(
                            sample_id=sm.id,
                            status=sm.status,
                            duration_seconds=sm.duration_seconds,
                            created_at=sm.created_at,
                        )
                        for sm in s.samples
                    ],
                )
                for s in items
            ],
            next_cursor=next_cursor,
        )

    async def get_speaker(self, user_id: str, speaker_id: UUID) -> SpeakerResponse:
        speaker = await self._repo.get_speaker(speaker_id, user_id)
        if speaker is None:
            raise NotFoundError(f"Speaker {speaker_id} not found")
        return SpeakerResponse(
            speaker_id=speaker.id,
            speaker_name=speaker.speaker_name,
            created_at=speaker.created_at,
            samples=[
                SampleResponse(
                    sample_id=sm.id,
                    status=sm.status,
                    duration_seconds=sm.duration_seconds,
                    created_at=sm.created_at,
                )
                for sm in speaker.samples
            ],
        )

    async def rename_speaker(self, user_id: str, speaker_id: UUID, name: str) -> SpeakerResponse:
        speaker = await self._repo.get_speaker(speaker_id, user_id)
        if speaker is None:
            raise NotFoundError(f"Speaker {speaker_id} not found")
        updated = await self._repo.update_speaker_name(speaker_id, name)
        return SpeakerResponse(
            speaker_id=updated.id,
            speaker_name=updated.speaker_name,
            created_at=updated.created_at,
        )

    async def delete_speaker(self, user_id: str, speaker_id: UUID) -> None:
        speaker = await self._repo.get_speaker(speaker_id, user_id)
        if speaker is None:
            raise NotFoundError(f"Speaker {speaker_id} not found")
        # Collect and delete all sample S3 keys (skip shared sample resources)
        sample_keys = [s.s3_key for s in speaker.samples if not s.s3_key.startswith("samples/")]
        if sample_keys:
            self._storage.delete_objects(sample_keys)
        await self._repo.delete_speaker(speaker_id)

    # ── Speaker Samples ───────────────────────────────────────────────────────

    async def initiate_sample_upload(
        self, user_id: str, speaker_id: UUID
    ) -> SampleUploadInitResponse:
        speaker = await self._repo.get_speaker(speaker_id, user_id)
        if speaker is None:
            raise NotFoundError(f"Speaker {speaker_id} not found")
        sample_id = uuid4()
        s3_key = f"audio/{user_id}/speakers/{speaker_id}/samples/{sample_id}"
        sample = await self._repo.create_sample(speaker_id, s3_key, sample_id)
        upload_url = self._storage.generate_presigned_upload_url(s3_key)
        return SampleUploadInitResponse(sample_id=sample.id, upload_url=upload_url)

    async def confirm_sample_upload(
        self, user_id: str, speaker_id: UUID, sample_id: UUID
    ) -> SampleResponse:
        speaker = await self._repo.get_speaker(speaker_id, user_id)
        if speaker is None:
            raise NotFoundError(f"Speaker {speaker_id} not found")
        sample = await self._repo.get_sample(sample_id, speaker_id)
        if sample is None:
            raise NotFoundError(f"Sample {sample_id} not found")
        # Download and validate (skipped in mock/dev mode where storage returns empty bytes)
        data = self._storage.get_object_bytes(sample.s3_key)
        duration_seconds: Optional[float] = None
        if data:
            try:
                audio = AudioSegment.from_file(io.BytesIO(data))
            except CouldntDecodeError:
                await self._repo.update_sample_status(sample_id, "failed")
                raise AudioValidationError("unsupported_format")
            duration_seconds = len(audio) / 1000.0
            if duration_seconds < 10:
                await self._repo.update_sample_status(sample_id, "failed")
                raise AudioValidationError("duration_too_short")
            if duration_seconds > 60:
                await self._repo.update_sample_status(sample_id, "failed")
                raise AudioValidationError("duration_too_long")
        await self._repo.update_sample_status(sample_id, "processing", duration_seconds=duration_seconds)
        await self._repo.db.commit()
        self._sqs.publish_sample_embedding(sample_id, sample.s3_key)
        return SampleResponse(
            sample_id=sample.id,
            status="processing",
            duration_seconds=duration_seconds,
            created_at=sample.created_at,
        )

    async def delete_sample(self, user_id: str, speaker_id: UUID, sample_id: UUID) -> None:
        speaker = await self._repo.get_speaker(speaker_id, user_id)
        if speaker is None:
            raise NotFoundError(f"Speaker {speaker_id} not found")
        sample = await self._repo.get_sample(sample_id, speaker_id)
        if sample is None:
            raise NotFoundError(f"Sample {sample_id} not found")
        # Skip deletion for shared sample resources
        if not sample.s3_key.startswith("samples/"):
            self._storage.delete_objects([sample.s3_key])
        await self._repo.delete_sample(sample_id)

    # ── Transcription Jobs ────────────────────────────────────────────────────

    async def initiate_job_upload(
        self, user_id: str, request: JobCreateRequest
    ) -> JobCreateResponse:
        active = await self._repo.count_active_jobs(user_id)
        if active >= self._settings.max_concurrent_jobs:
            raise ConcurrentJobLimitExceeded()
        job_id = uuid4()
        s3_key = f"audio/{user_id}/{job_id}/source"
        job = await self._repo.create_job(
            user_id=user_id,
            audio_s3_key=s3_key,
            speaker_count_hint=request.speaker_count_hint,
            language=request.language,
            speaker_ids=request.speaker_ids,
        )
        await self._repo.append_event(job.id, "api", "job.created")
        upload_url = self._storage.generate_presigned_upload_url(s3_key)
        await self._repo.append_event(job.id, "api", "upload_url.generated")
        return JobCreateResponse(job_id=job.id, upload_url=upload_url)

    async def confirm_job_upload(
        self, user_id: str, job_id: UUID, speaker_ids: Optional[list[UUID]] = None
    ) -> None:
        job = await self._repo.get_job(job_id, user_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        if job.status != "pending":
            raise ConflictError("Job is not in pending state")
        if not self._storage.object_exists(job.audio_s3_key):
            raise AudioUploadMissing()
        effective_speaker_ids: list[UUID] = (
            speaker_ids if speaker_ids is not None
            else [UUID(s) for s in (job.speaker_ids or [])]
        )
        if effective_speaker_ids:
            unready = await self._repo.get_speakers_without_ready_samples(effective_speaker_ids)
            if unready:
                raise ConflictError("Speaker samples are still processing — try again shortly")
        await self._repo.append_event(job_id, "api", "audio.verified")
        aws_job_name, transcribe_output_key = self._storage.start_transcription_job(
            job_id=str(job_id),
            audio_s3_key=job.audio_s3_key,
            user_id=user_id,
            speaker_count_hint=job.speaker_count_hint,
            language=job.language,
        )
        await self._repo.append_event(job_id, "api", "transcribe.started", {"aws_job_name": aws_job_name})
        await self._repo.update_job_status(
            job_id,
            "transcribing",
            aws_transcribe_job_name=aws_job_name,
            transcribe_output_s3_key=transcribe_output_key,
        )
        await self._repo.db.commit()
        self._sqs.publish_transcription_job(
            job_id, aws_job_name, speaker_ids if speaker_ids is not None else job.speaker_ids
        )
        await self._repo.append_event(job_id, "api", "sqs.published")
        await self._repo.db.commit()
        if self._gpu is not None:
            try:
                await self._gpu.ensure_worker("job", user_id, job_id=job_id)
                await self._repo.append_event(job_id, "api", "gpu.ensured")
            except GpuCapExceeded as e:
                await self._repo.append_event(job_id, "api", "gpu.capped", {"reason": e.reason})
            await self._repo.db.commit()

    async def rerun_job(self, user_id: str, job_id: UUID) -> JobStatusResponse:
        """Create a fresh job that reuses a completed/failed job's audio and re-runs the pipeline.

        The bucket lifecycle expires audio objects, so existence is checked before the new job
        row is created — a stale rerun 404s cleanly instead of leaving an orphaned pending job.

        The audio is server-side copied to a key owned by the new job, rather than aliasing the
        source job's key: `delete_job` unconditionally deletes a job's `audio_s3_key`, so sharing
        the key would mean deleting either job destroys the other's audio. The one exception is a
        `samples/` key, which is shared by design and never deleted — those are passed through
        uncopied.
        """
        active = await self._repo.count_active_jobs(user_id)
        if active >= self._settings.max_concurrent_jobs:
            raise ConcurrentJobLimitExceeded()
        source = await self._repo.get_job(job_id, user_id)
        if source is None:
            raise NotFoundError(f"Job {job_id} not found")
        if source.status not in ("complete", "failed"):
            raise ConflictError("Job is still running — wait for it to finish before rerunning")
        if not source.audio_s3_key:
            raise ConflictError("Job has no audio to rerun")
        if not self._storage.object_exists(source.audio_s3_key):
            raise NotFoundError(
                "Audio for this job is no longer available — it may have expired from storage"
            )

        if source.audio_s3_key.startswith("samples/"):
            new_audio_key = source.audio_s3_key
        else:
            new_audio_key = f"audio/{user_id}/{uuid4()}/source"
            self._storage.copy_object(source.audio_s3_key, new_audio_key)

        speaker_ids = [UUID(s) for s in source.speaker_ids] if source.speaker_ids else None
        new_job = await self._repo.create_job(
            user_id=user_id,
            audio_s3_key=new_audio_key,
            speaker_count_hint=source.speaker_count_hint,
            language=source.language,
            speaker_ids=speaker_ids,
        )
        await self._repo.append_event(new_job.id, "api", "job.created", {"rerun_of": str(job_id)})
        await self.confirm_job_upload(user_id, new_job.id, speaker_ids)
        return await self.get_job_status(user_id, new_job.id)

    async def get_job_status(self, user_id: str, job_id: UUID) -> JobStatusResponse:
        job = await self._repo.get_job(job_id, user_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        partial_available = (
            job.status == "failed" and job.transcribe_output_s3_key is not None
        )
        gpu_state = None
        if self._gpu is not None and job.status in ("transcribing", "matching"):
            gpu_state = await self._gpu.get_state()
            if gpu_state.worker_state == "off":
                try:
                    gpu_state = await self._gpu.ensure_worker("resume", user_id)
                except GpuCapExceeded as e:
                    gpu_state = gpu_state.model_copy(update={"notice": e.reason})
        return JobStatusResponse(
            job_id=job.id,
            status=job.status,
            speaker_count_hint=job.speaker_count_hint,
            language=job.language,
            speaker_ids=job.speaker_ids or [],
            error_message=job.error_message,
            partial_transcript_available=partial_available,
            matched_speaker_count=job.matched_speaker_count,
            total_segment_count=job.total_segment_count,
            created_at=job.created_at,
            updated_at=job.updated_at,
            completed_at=job.completed_at,
            worker_state=gpu_state.worker_state if gpu_state else None,
            estimated_wait_seconds=gpu_state.estimated_wait_seconds if gpu_state else None,
            gpu_notice=gpu_state.notice if gpu_state else None,
            is_public=job.is_public,
        )

    async def list_jobs(
        self, user_id: str, cursor: Optional[str], limit: int
    ) -> JobListResponse:
        items, next_cursor = await self._repo.list_jobs(user_id, cursor, limit)
        return JobListResponse(
            items=[
                JobStatusResponse(
                    job_id=j.id,
                    status=j.status,
                    speaker_count_hint=j.speaker_count_hint,
                    language=j.language,
                    speaker_ids=j.speaker_ids or [],
                    error_message=j.error_message,
                    partial_transcript_available=(
                        j.status == "failed" and j.transcribe_output_s3_key is not None
                    ),
                    matched_speaker_count=j.matched_speaker_count,
                    total_segment_count=j.total_segment_count,
                    created_at=j.created_at,
                    updated_at=j.updated_at,
                    completed_at=j.completed_at,
                    is_public=j.is_public,
                )
                for j in items
            ],
            next_cursor=next_cursor,
        )

    async def get_transcript(self, user_id: str, job_id: UUID) -> TranscriptResponse:
        job = await self._repo.get_job(job_id, user_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        if job.status in ("pending", "transcribing", "matching"):
            raise ConflictError("Transcript not yet available")
        segments = await self._repo.get_segments(job_id)
        segment_responses = []
        for seg in segments:
            speaker_name = None
            if seg.speaker_profile is not None:
                speaker_name = seg.speaker_profile.speaker_name
            segment_responses.append(
                SegmentResponse(
                    segment_id=seg.id,
                    anonymous_label=seg.anonymous_label,
                    speaker_name=speaker_name,
                    start_time=seg.start_time,
                    end_time=seg.end_time,
                    text=seg.text,
                )
            )
        if job.status == "complete":
            return TranscriptResponse(segments=segment_responses)
        # failed with partial data
        if job.transcribe_output_s3_key:
            return TranscriptResponse(segments=segment_responses)
        raise ConflictError("No transcript available")

    async def get_job_events(self, user_id: str, job_id: UUID) -> list[JobEventResponse]:
        job = await self._repo.get_job(job_id, user_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        events = await self._repo.get_events(job_id)
        return [
            JobEventResponse(
                id=e.id,
                job_id=e.job_id,
                occurred_at=e.occurred_at,
                source=e.source,
                event=e.event,
                detail=e.detail,
            )
            for e in events
        ]

    async def get_turn_distances(self, user_id: str, job_id: UUID) -> TurnDistancesResponse:
        job = await self._repo.get_job(job_id, user_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        rows = await self._repo.get_turn_distances(job_id)
        turns_dict: dict[tuple, dict] = {}
        for row in rows:
            turn_dist = row[0]
            speaker_name = row[1]
            key = (turn_dist.start_time, turn_dist.end_time)
            if key not in turns_dict:
                turns_dict[key] = {
                    "start_time": turn_dist.start_time,
                    "end_time": turn_dist.end_time,
                    "text": turn_dist.text,
                    "candidates": [],
                }
            turns_dict[key]["candidates"].append(
                TurnCandidateResponse(
                    candidate_id=turn_dist.candidate_id,
                    speaker_name=speaker_name,
                    cosine_dist=turn_dist.cosine_dist,
                )
            )
        return TurnDistancesResponse(
            turns=[TurnDistanceResponse(**t) for t in turns_dict.values()]
        )

    async def delete_job(self, user_id: str, job_id: UUID) -> None:
        job = await self._repo.get_job(job_id, user_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        # Skip shared sample resources; only delete per-job S3 objects
        s3_keys = [
            k for k in [job.audio_s3_key, job.transcribe_output_s3_key]
            if k and not k.startswith("samples/")
        ]
        # Also clean up any segment audio files that the worker may not have deleted
        segment_prefix = f"audio/{user_id}/{job_id}/segments/"
        s3_keys.extend(self._storage.list_keys_with_prefix(segment_prefix))
        self._storage.delete_objects(s3_keys)
        await self._repo.delete_job(job_id)

    async def set_visibility(
        self, user_id: str, job_id: UUID, is_public: bool
    ) -> JobStatusResponse:
        job = await self._repo.set_is_public(job_id, user_id, is_public)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        return await self.get_job_status(user_id, job_id)

    async def get_job_audio_url(self, user_id: str, job_id: UUID) -> AudioUrlResponse:
        """Presigned playback + download URLs for a job's raw input audio.

        Object existence is checked (same bucket-lifecycle reality `rerun_job` handles) so a
        stale request 404s cleanly instead of handing back a presigned URL to a 404 on S3.
        """
        job = await self._repo.get_job(job_id, user_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        if not job.audio_s3_key:
            raise NotFoundError("Job has no input audio")
        if not self._storage.object_exists(job.audio_s3_key):
            raise NotFoundError(
                "Input audio is no longer available — it may have expired from storage"
            )
        filename = f"job-{job_id}-audio"
        presign = self._storage.generate_presigned_download_url
        return AudioUrlResponse(
            url=presign(job.audio_s3_key, ttl_seconds=DOWNLOAD_TTL_SECONDS),
            download_url=presign(
                job.audio_s3_key, ttl_seconds=DOWNLOAD_TTL_SECONDS, attachment_filename=filename,
            ),
            filename=filename,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=DOWNLOAD_TTL_SECONDS),
        )

    async def get_sample_audio_url(
        self, user_id: str, speaker_id: UUID, sample_id: UUID
    ) -> AudioUrlResponse:
        """Presigned playback + download URLs for a speaker enrollment sample.

        Ownership goes through the speaker, like the other sample endpoints. Any sample
        status may be fetched here — the SPA is the one that only offers this for `ready`
        samples.
        """
        speaker = await self._repo.get_speaker(speaker_id, user_id)
        if speaker is None:
            raise NotFoundError(f"Speaker {speaker_id} not found")
        sample = await self._repo.get_sample(sample_id, speaker_id)
        if sample is None:
            raise NotFoundError(f"Sample {sample_id} not found")
        if not self._storage.object_exists(sample.s3_key):
            raise NotFoundError(
                "Sample audio is no longer available — it may have expired from storage"
            )
        filename = f"speaker-sample-{sample_id}"
        presign = self._storage.generate_presigned_download_url
        return AudioUrlResponse(
            url=presign(sample.s3_key, ttl_seconds=DOWNLOAD_TTL_SECONDS),
            download_url=presign(
                sample.s3_key, ttl_seconds=DOWNLOAD_TTL_SECONDS, attachment_filename=filename,
            ),
            filename=filename,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=DOWNLOAD_TTL_SECONDS),
        )

    # ── Sample Job ────────────────────────────────────────────────────────────

    async def create_sample_job(self, user_id: str) -> SampleJobResponse:
        """Create a transcription job using the pre-uploaded shared sample audio files.

        No S3 upload is required — the job references the shared sample S3 keys directly
        and is immediately confirmed (transitions to transcribing).
        """
        active = await self._repo.count_active_jobs(user_id)
        if active >= self._settings.max_concurrent_jobs:
            raise ConcurrentJobLimitExceeded()

        # Create speaker profiles for the sample speakers
        barry = await self._repo.create_speaker(user_id, "Barry")
        jane = await self._repo.create_speaker(user_id, "Jane")

        # Create speaker samples pointing to shared S3 keys (already status="processing")
        barry_sample = await self._repo.create_sample(barry.id, self._settings.sample_barry_s3_key)
        jane_sample = await self._repo.create_sample(jane.id, self._settings.sample_jane_s3_key)

        # Commit samples before publishing SQS so the worker can find them in the DB
        await self._repo.db.commit()

        # Publish SQS messages so the worker computes embeddings from the shared files
        self._sqs.publish_sample_embedding(barry_sample.id, barry_sample.s3_key)
        self._sqs.publish_sample_embedding(jane_sample.id, jane_sample.s3_key)

        # Create a job pointing to the shared audio file
        speaker_ids = [barry.id, jane.id]
        job = await self._repo.create_job(
            user_id=user_id,
            audio_s3_key=self._settings.sample_audio_s3_key,
            speaker_count_hint=2,
            language="en-US",
            speaker_ids=speaker_ids,
        )

        # Confirm immediately — no upload needed, file is already in S3
        aws_job_name, transcribe_output_key = self._storage.start_transcription_job(
            job_id=str(job.id),
            audio_s3_key=self._settings.sample_audio_s3_key,
            user_id=user_id,
            speaker_count_hint=2,
            language="en-US",
        )
        await self._repo.update_job_status(
            job.id,
            "transcribing",
            aws_transcribe_job_name=aws_job_name,
            transcribe_output_s3_key=transcribe_output_key,
        )
        await self._repo.db.commit()
        self._sqs.publish_transcription_job(job.id, aws_job_name, speaker_ids)

        return SampleJobResponse(job_id=job.id, speaker_ids=speaker_ids)

    async def get_samples(self) -> SamplePreviewResponse:
        """The bundled sample: what NewJobForm previews in sample-review mode before Start."""
        keys = [
            self._settings.sample_audio_s3_key,
            self._settings.sample_barry_s3_key,
            self._settings.sample_jane_s3_key,
        ]
        if not all(self._storage.object_exists(k) for k in keys):
            raise ConflictError("Sample audio has not been uploaded")
        presign = self._storage.generate_presigned_download_url
        return SamplePreviewResponse(
            name="Sample conversation",
            audio=SampleAudioItem(
                filename=Path(self._settings.sample_audio_s3_key).stem,
                url=presign(self._settings.sample_audio_s3_key),
            ),
            speakers=[
                SampleSpeakerItem(
                    speaker_name="Barry", url=presign(self._settings.sample_barry_s3_key)
                ),
                SampleSpeakerItem(
                    speaker_name="Jane", url=presign(self._settings.sample_jane_s3_key)
                ),
            ],
        )


ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "transcribe"


class LocalTranscriptionService(TranscriptionService):
    """TranscriptionService variant for local dev (USE_MOCK_TRANSCRIPTION=true).

    Uses the real PostgreSQL database for persistence but skips all AWS calls.
    confirm_job_upload immediately marks jobs as complete and seeds mock segments.
    confirm_sample_upload returns processing then transitions to ready after a
    configurable delay (MOCK_SAMPLE_PROCESSING_DELAY_SECONDS, default 3 s).
    """

    async def confirm_sample_upload(
        self, user_id: str, speaker_id: UUID, sample_id: UUID
    ) -> SampleResponse:
        speaker = await self._repo.get_speaker(speaker_id, user_id)
        if speaker is None:
            raise NotFoundError(f"Speaker {speaker_id} not found")
        sample = await self._repo.get_sample(sample_id, speaker_id)
        if sample is None:
            raise NotFoundError(f"Sample {sample_id} not found")
        await self._repo.update_sample_status(sample_id, "processing", duration_seconds=30.0)
        if not self._settings.mock_worker_external:
            asyncio.create_task(self._mock_process_sample(sample_id))
        return SampleResponse(
            sample_id=sample.id,
            status="processing",
            duration_seconds=30.0,
            created_at=sample.created_at,
        )

    async def _mock_process_sample(self, sample_id: UUID) -> None:
        import app.db.session as db_session
        await asyncio.sleep(self._settings.mock_sample_processing_delay_seconds)
        async with db_session.AsyncSessionLocal() as session:
            try:
                repo = TranscriptionRepository(session)
                await repo.update_sample_status(sample_id, "ready")
                await session.commit()
            except Exception:
                await session.rollback()

    async def confirm_job_upload(
        self, user_id: str, job_id: UUID, speaker_ids: Optional[list[UUID]] = None
    ) -> None:
        job = await self._repo.get_job(job_id, user_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        if job.status != "pending":
            raise ConflictError("Job is not in pending state")
        await self._repo.append_event(job_id, "api", "audio.verified")
        await self._repo.append_event(job_id, "api", "transcribe.started", {"aws_job_name": f"mock-job-{job_id}"})
        await self._repo.update_job_status(
            job_id,
            "transcribing",
            aws_transcribe_job_name=f"mock-job-{job_id}",
            transcribe_output_s3_key=f"audio/{user_id}/{job_id}/transcript_raw.json",
        )
        await self._repo.append_event(job_id, "api", "sqs.published")
        if not self._settings.mock_worker_external:
            asyncio.create_task(self._mock_process_job(user_id, job_id))

    async def _mock_process_job(self, user_id: str, job_id: UUID) -> None:
        import app.db.session as db_session

        await asyncio.sleep(self._settings.mock_job_transcribing_delay_seconds)
        async with db_session.AsyncSessionLocal() as session:
            try:
                repo = TranscriptionRepository(session)
                await repo.append_event(job_id, "worker", "worker.received")
                await repo.append_event(job_id, "worker", "transcribe.polling")
                await repo.append_event(job_id, "worker", "transcribe.complete")
                await repo.append_event(job_id, "worker", "audio.fetched")
                await repo.append_event(job_id, "worker", "diarization.complete")
                await repo.append_event(job_id, "worker", "alignment.complete")
                await repo.update_job_status(job_id, "matching")
                await session.commit()
            except Exception:
                await session.rollback()
                return

        await asyncio.sleep(self._settings.mock_job_matching_delay_seconds)
        async with db_session.AsyncSessionLocal() as session:
            try:
                repo = TranscriptionRepository(session)
                mock_segments = [
                    {"job_id": job_id, "anonymous_label": "Speaker 1", "start_time": 0.0, "end_time": 4.5, "text": "Hello, welcome to the meeting."},
                    {"job_id": job_id, "anonymous_label": "Speaker 2", "start_time": 4.8, "end_time": 9.2, "text": "Thanks for joining. Let's get started."},
                    {"job_id": job_id, "anonymous_label": "Speaker 1", "start_time": 9.5, "end_time": 15.0, "text": "Sure. First agenda item is the quarterly review."},
                    {"job_id": job_id, "anonymous_label": "Speaker 2", "start_time": 15.3, "end_time": 21.8, "text": "Right. Numbers look good overall, up about twelve percent quarter on quarter."},
                ]
                await repo.create_segments(mock_segments)
                await repo.append_event(job_id, "worker", "segments.inserted", {"count": len(mock_segments)})
                await repo.update_job_status(
                    job_id,
                    "complete",
                )
                await repo.append_event(job_id, "worker", "job.complete")
                await session.commit()
            except Exception:
                await session.rollback()

    async def create_sample_job(self, user_id: str) -> SampleJobResponse:
        active = await self._repo.count_active_jobs(user_id)
        if active >= self._settings.max_concurrent_jobs:
            raise ConcurrentJobLimitExceeded()

        barry = await self._repo.create_speaker(user_id, "Barry")
        jane = await self._repo.create_speaker(user_id, "Jane")

        barry_sample = await self._repo.create_sample(barry.id, self._settings.sample_barry_s3_key)
        jane_sample = await self._repo.create_sample(jane.id, self._settings.sample_jane_s3_key)

        if not self._settings.mock_worker_external:
            asyncio.create_task(self._mock_process_sample(barry_sample.id))
            asyncio.create_task(self._mock_process_sample(jane_sample.id))

        speaker_ids = [barry.id, jane.id]
        job = await self._repo.create_job(
            user_id=user_id,
            audio_s3_key=self._settings.sample_audio_s3_key,
            speaker_count_hint=2,
            language="en-US",
            speaker_ids=speaker_ids,
        )

        await self._repo.update_job_status(
            job.id,
            "transcribing",
            aws_transcribe_job_name=f"mock-job-{job.id}",
            transcribe_output_s3_key=f"audio/{user_id}/{job.id}/transcript_raw.json",
        )
        if not self._settings.mock_worker_external:
            asyncio.create_task(self._mock_process_job(user_id, job.id))

        return SampleJobResponse(job_id=job.id, speaker_ids=speaker_ids)

    async def get_samples(self) -> SamplePreviewResponse:
        """Seed the committed sample audio into the dev sink once, then list it like prod."""
        seeds = {
            self._settings.sample_audio_s3_key: ASSET_DIR / "conversation.wav",
            self._settings.sample_barry_s3_key: ASSET_DIR / "barry.wav",
            self._settings.sample_jane_s3_key: ASSET_DIR / "jane.wav",
        }
        for key, path in seeds.items():
            if not self._storage.object_exists(key):
                self._storage.write_object(key, path.read_bytes())
        return await super().get_samples()
