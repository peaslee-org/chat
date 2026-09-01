import base64
import json
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.transcription import SpeakerProfile, SpeakerSample, TranscriptionJob, TranscriptSegment, TranscriptionJobEvent, TranscriptTurnDistance


class TranscriptionRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Speaker Profiles ──────────────────────────────────────────────────────

    async def create_speaker(self, user_id: str, name: str) -> SpeakerProfile:
        speaker = SpeakerProfile(user_id=user_id, speaker_name=name)
        self.db.add(speaker)
        await self.db.flush()
        return speaker

    async def get_speaker(self, speaker_id: UUID, user_id: str) -> Optional[SpeakerProfile]:
        result = await self.db.execute(
            select(SpeakerProfile)
            .options(selectinload(SpeakerProfile.samples))
            .where(
                SpeakerProfile.id == speaker_id,
                SpeakerProfile.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_speakers(
        self, user_id: str, cursor: Optional[str], limit: int
    ) -> tuple[List[SpeakerProfile], Optional[str]]:
        query = (
            select(SpeakerProfile)
            .options(selectinload(SpeakerProfile.samples))
            .where(SpeakerProfile.user_id == user_id)
        )
        if cursor:
            cursor_data = json.loads(base64.b64decode(cursor).decode())
            cursor_dt = datetime.fromisoformat(cursor_data["created_at"])
            cursor_id = UUID(cursor_data["id"])
            query = query.where(
                or_(
                    SpeakerProfile.created_at < cursor_dt,
                    and_(
                        SpeakerProfile.created_at == cursor_dt,
                        SpeakerProfile.id < cursor_id,
                    ),
                )
            )
        query = (
            query.order_by(SpeakerProfile.created_at.desc(), SpeakerProfile.id.desc())
            .limit(limit + 1)
        )
        result = await self.db.execute(query)
        items = list(result.scalars().all())
        next_cursor = None
        if len(items) > limit:
            last = items.pop()
            next_cursor = base64.b64encode(
                json.dumps({"created_at": last.created_at.isoformat(), "id": str(last.id)}).encode()
            ).decode()
        return items, next_cursor

    async def update_speaker_name(self, speaker_id: UUID, name: str) -> Optional[SpeakerProfile]:
        speaker = await self.db.get(SpeakerProfile, speaker_id)
        if speaker is None:
            return None
        speaker.speaker_name = name
        await self.db.flush()
        return speaker

    async def delete_speaker(self, speaker_id: UUID) -> None:
        result = await self.db.execute(
            select(SpeakerProfile).where(SpeakerProfile.id == speaker_id)
        )
        speaker = result.scalar_one_or_none()
        if speaker:
            await self.db.delete(speaker)

    # ── Speaker Samples ───────────────────────────────────────────────────────

    async def create_sample(
        self, speaker_profile_id: UUID, s3_key: str, sample_id: Optional[UUID] = None
    ) -> SpeakerSample:
        sample = SpeakerSample(
            **({"id": sample_id} if sample_id is not None else {}),
            speaker_profile_id=speaker_profile_id,
            s3_key=s3_key,
            status="processing",
        )
        self.db.add(sample)
        await self.db.flush()
        return sample

    async def get_sample(
        self, sample_id: UUID, speaker_profile_id: UUID
    ) -> Optional[SpeakerSample]:
        result = await self.db.execute(
            select(SpeakerSample).where(
                SpeakerSample.id == sample_id,
                SpeakerSample.speaker_profile_id == speaker_profile_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_sample_status(
        self,
        sample_id: UUID,
        status: str,
        duration_seconds: Optional[float] = None,
    ) -> None:
        result = await self.db.execute(
            select(SpeakerSample).where(SpeakerSample.id == sample_id)
        )
        sample = result.scalar_one_or_none()
        if sample:
            sample.status = status
            if duration_seconds is not None:
                sample.duration_seconds = duration_seconds

    async def delete_sample(self, sample_id: UUID) -> None:
        result = await self.db.execute(
            select(SpeakerSample).where(SpeakerSample.id == sample_id)
        )
        sample = result.scalar_one_or_none()
        if sample:
            await self.db.delete(sample)

    async def get_speakers_without_ready_samples(
        self, speaker_ids: list[UUID]
    ) -> list[UUID]:
        """Return the subset of speaker_ids that have no ready sample."""
        if not speaker_ids:
            return []
        result = await self.db.execute(
            select(SpeakerSample.speaker_profile_id)
            .where(
                SpeakerSample.speaker_profile_id.in_(speaker_ids),
                SpeakerSample.status == "ready",
            )
            .distinct()
        )
        ready_ids = {row[0] for row in result.all()}
        return [sid for sid in speaker_ids if sid not in ready_ids]

    # ── Transcription Jobs ────────────────────────────────────────────────────

    async def create_job(
        self,
        user_id: str,
        audio_s3_key: str,
        speaker_count_hint: Optional[int],
        language: str,
        speaker_ids: Optional[list[UUID]] = None,
    ) -> TranscriptionJob:
        job = TranscriptionJob(
            user_id=user_id,
            audio_s3_key=audio_s3_key,
            speaker_count_hint=speaker_count_hint,
            language=language,
            status="pending",
            speaker_ids=[str(sid) for sid in speaker_ids] if speaker_ids else [],
        )
        self.db.add(job)
        await self.db.flush()
        return job

    async def get_job(self, job_id: UUID, user_id: str) -> Optional[TranscriptionJob]:
        result = await self.db.execute(
            select(TranscriptionJob).where(
                TranscriptionJob.id == job_id,
                TranscriptionJob.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def count_active_jobs(self, user_id: str) -> int:
        result = await self.db.execute(
            select(func.count()).where(
                TranscriptionJob.user_id == user_id,
                TranscriptionJob.status.in_(["pending", "transcribing", "matching"]),
            )
        )
        return result.scalar_one()

    async def update_job_status(
        self,
        job_id: UUID,
        status: str,
        aws_transcribe_job_name: Optional[str] = None,
        transcribe_output_s3_key: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        result = await self.db.execute(
            select(TranscriptionJob).where(TranscriptionJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job:
            job.status = status
            if aws_transcribe_job_name is not None:
                job.aws_transcribe_job_name = aws_transcribe_job_name
            if transcribe_output_s3_key is not None:
                job.transcribe_output_s3_key = transcribe_output_s3_key
            if error_message is not None:
                job.error_message = error_message
            if status == "complete":
                job.completed_at = datetime.now(timezone.utc)

    async def list_jobs(
        self, user_id: str, cursor: Optional[str], limit: int
    ) -> tuple[List[TranscriptionJob], Optional[str]]:
        query = select(TranscriptionJob).where(TranscriptionJob.user_id == user_id)
        if cursor:
            cursor_data = json.loads(base64.b64decode(cursor).decode())
            cursor_dt = datetime.fromisoformat(cursor_data["created_at"])
            cursor_id = UUID(cursor_data["id"])
            query = query.where(
                or_(
                    TranscriptionJob.created_at < cursor_dt,
                    and_(
                        TranscriptionJob.created_at == cursor_dt,
                        TranscriptionJob.id < cursor_id,
                    ),
                )
            )
        query = (
            query.order_by(TranscriptionJob.created_at.desc(), TranscriptionJob.id.desc())
            .limit(limit + 1)
        )
        result = await self.db.execute(query)
        items = list(result.scalars().all())
        next_cursor = None
        if len(items) > limit:
            last = items.pop()
            next_cursor = base64.b64encode(
                json.dumps({"created_at": last.created_at.isoformat(), "id": str(last.id)}).encode()
            ).decode()
        return items, next_cursor

    async def delete_job(self, job_id: UUID) -> None:
        result = await self.db.execute(
            select(TranscriptionJob).where(TranscriptionJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job:
            await self.db.delete(job)

    async def list_public_jobs(self, limit: int = 20) -> List[TranscriptionJob]:
        result = await self.db.execute(
            select(TranscriptionJob)
            .where(TranscriptionJob.is_public.is_(True))
            .order_by(TranscriptionJob.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def get_public_job(self, job_id: UUID) -> Optional[TranscriptionJob]:
        result = await self.db.execute(
            select(TranscriptionJob).where(
                TranscriptionJob.id == job_id,
                TranscriptionJob.is_public.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def set_is_public(self, job_id: UUID, user_id: str, value: bool) -> Optional[TranscriptionJob]:
        job = await self.get_job(job_id, user_id)
        if job is None:
            return None
        job.is_public = value
        await self.db.flush()
        return job

    async def get_segment_stats(self, job_id: UUID) -> tuple[Optional[float], int]:
        result = await self.db.execute(
            select(func.max(TranscriptSegment.end_time), func.count(TranscriptSegment.id)).where(
                TranscriptSegment.job_id == job_id
            )
        )
        duration, count = result.one()
        return duration, count

    # ── Transcript Segments ───────────────────────────────────────────────────

    async def get_segments(self, job_id: UUID) -> List[TranscriptSegment]:
        result = await self.db.execute(
            select(TranscriptSegment)
            .options(selectinload(TranscriptSegment.speaker_profile))
            .where(TranscriptSegment.job_id == job_id)
            .order_by(TranscriptSegment.start_time.asc())
        )
        return list(result.scalars().all())

    async def create_segments(
        self,
        segments: list[dict],
    ) -> None:
        """Insert TranscriptSegment rows directly. Each dict must include job_id,
        anonymous_label, start_time, end_time, and text."""
        for seg_data in segments:
            self.db.add(TranscriptSegment(**seg_data))
        await self.db.flush()

    # ── Job Events ────────────────────────────────────────────────────────────

    async def append_event(
        self,
        job_id: UUID,
        source: str,
        event: str,
        detail: Optional[dict] = None,
    ) -> TranscriptionJobEvent:
        ev = TranscriptionJobEvent(job_id=job_id, source=source, event=event, detail=detail)
        self.db.add(ev)
        await self.db.flush()
        return ev

    async def get_turn_distances(self, job_id: UUID) -> list:
        result = await self.db.execute(
            select(TranscriptTurnDistance, SpeakerProfile.speaker_name)
            .outerjoin(SpeakerProfile, TranscriptTurnDistance.candidate_id == SpeakerProfile.id)
            .where(TranscriptTurnDistance.job_id == job_id)
            .order_by(TranscriptTurnDistance.start_time.asc())
        )
        return list(result.all())

    async def get_events(
        self, job_id: UUID, after_id: int = 0
    ) -> list[TranscriptionJobEvent]:
        result = await self.db.execute(
            select(TranscriptionJobEvent)
            .where(
                TranscriptionJobEvent.job_id == job_id,
                TranscriptionJobEvent.id > after_id,
            )
            .order_by(TranscriptionJobEvent.id.asc())
        )
        return list(result.scalars().all())
