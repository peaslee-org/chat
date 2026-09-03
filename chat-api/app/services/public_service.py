"""Read-only assembly for the unauthenticated /api/v1/public router.

Rule: a non-public id and a missing id raise the same NotFoundError — the
public surface must not reveal that a private row exists.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from app.core.exceptions import NotFoundError
from app.schemas.public import (
    PublicConversationDetail,
    PublicConversationSummary,
    PublicMessage,
    PublicScanDetail,
    PublicScanSummary,
    PublicTranscriptionDetail,
    PublicTranscriptionSummary,
    ShowcaseResponse,
)
from app.schemas.transcription import CompileSettings, SegmentResponse
from app.services.photogrammetry_service import DOWNLOAD_TTL_SECONDS
from app.services.transcript_compiler import load_or_compile, transcript_response

SHOWCASE_LIMIT = 20


class PublicService:
    def __init__(self, scans, transcriptions, conversations, storage, compile_defaults: CompileSettings | None = None):
        self._scans = scans
        self._transcriptions = transcriptions
        self._conversations = conversations
        self._storage = storage
        self._compile_defaults = compile_defaults or CompileSettings()

    async def showcase(self) -> ShowcaseResponse:
        scans = [self._scan_summary(j) for j in await self._scans.list_public_jobs(SHOWCASE_LIMIT)]
        transcription_jobs = await self._transcriptions.list_public_jobs(SHOWCASE_LIMIT)
        stats = await self._transcriptions.get_segment_stats_bulk([j.id for j in transcription_jobs])
        transcriptions = [
            self._transcription_summary(j, stats.get(j.id, (None, 0)))
            for j in transcription_jobs
        ]
        conversations = [
            PublicConversationSummary(
                conversation_id=c.id, title=c.title, model_id=c.model_id, created_at=c.created_at
            )
            for c in await self._conversations.list_public(SHOWCASE_LIMIT)
        ]
        return ShowcaseResponse(scans=scans, transcriptions=transcriptions, conversations=conversations)

    async def scan_detail(self, job_id: UUID) -> PublicScanDetail:
        job = await self._scans.get_public_job(job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        mesh_url = expires_at = None
        if job.status == "complete" and job.mesh_s3_key:
            mesh_url = self._storage.generate_presigned_download_url(job.mesh_s3_key, DOWNLOAD_TTL_SECONDS)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=DOWNLOAD_TTL_SECONDS)
        matched = (
            sum(1 for s in job.photo_status.values() if s == "registered")
            if job.photo_status
            else None
        )
        return PublicScanDetail(
            **self._scan_summary(job).model_dump(),
            warnings=list(job.warnings or []),
            matched=matched,
            total=job.image_count,
            mesh_url=mesh_url,
            expires_at=expires_at,
            completed_at=job.completed_at,
        )

    async def transcription_detail(self, job_id: UUID) -> PublicTranscriptionDetail:
        job = await self._transcriptions.get_public_job(job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        stats = await self._transcriptions.get_segment_stats(job_id)
        summary = self._transcription_summary(job, stats)
        segments = [
            SegmentResponse(
                segment_id=s.id,
                anonymous_label=s.anonymous_label,
                speaker_name=s.speaker_profile.speaker_name if s.speaker_profile else None,
                start_time=s.start_time,
                end_time=s.end_time,
                text=s.text,
            )
            for s in await self._transcriptions.get_segments(job_id)
        ]
        compiled = await load_or_compile(self._transcriptions, job_id, self._compile_defaults)
        await self._transcriptions.db.commit()
        tr = transcript_response(segments, compiled, self._compile_defaults)
        return PublicTranscriptionDetail(
            **summary.model_dump(),
            segments=tr.segments,
            turns=tr.turns,
            settings=tr.settings,
            compiled_at=tr.compiled_at,
        )

    async def conversation_detail(self, conversation_id: UUID) -> PublicConversationDetail:
        conversation = await self._conversations.get_public(conversation_id)
        if conversation is None:
            raise NotFoundError(f"Conversation {conversation_id} not found")
        messages = [
            PublicMessage(role=m.role, content=m.content, created_at=m.created_at)
            for m in await self._conversations.get_messages(conversation_id)
        ]
        return PublicConversationDetail(
            conversation_id=conversation.id,
            title=conversation.title,
            model_id=conversation.model_id,
            created_at=conversation.created_at,
            messages=messages,
        )

    def _scan_summary(self, job) -> PublicScanSummary:
        preview_url = (
            self._storage.generate_presigned_download_url(job.preview_s3_key, DOWNLOAD_TTL_SECONDS)
            if job.preview_s3_key
            else None
        )
        return PublicScanSummary(
            job_id=job.id,
            name=job.name,
            image_count=job.image_count,
            status=job.status,
            preview_url=preview_url,
            created_at=job.created_at,
        )

    def _transcription_summary(
        self, job, stats: tuple[Optional[float], int]
    ) -> PublicTranscriptionSummary:
        duration, count = stats
        return PublicTranscriptionSummary(
            job_id=job.id,
            created_at=job.created_at,
            duration_seconds=duration,
            segment_count=count or None,
            speaker_count=job.matched_speaker_count,
        )
