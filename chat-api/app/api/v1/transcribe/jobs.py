import asyncio
import json
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.api.v1.transcribe.deps import get_transcription_service
from app.core.security import verify_cognito_token
from app.dependencies import get_current_user
from app.repositories.transcription import TranscriptionRepository
from app.schemas.public import VisibilityRequest
from app.schemas.transcription import (
    JobCreateRequest,
    JobCreateResponse,
    JobEventResponse,
    JobListResponse,
    JobStatusResponse,
    SampleJobResponse,
    TranscriptResponse,
    TurnDistancesResponse,
)
from app.services.transcription_service import TranscriptionService
import app.db.session as db_session

router = APIRouter()


@router.post("/jobs/sample", status_code=202, response_model=SampleJobResponse)
async def create_sample_job(
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> SampleJobResponse:
    return await service.create_sample_job(current_user["sub"])


@router.post("/jobs", status_code=202, response_model=JobCreateResponse)
async def initiate_job_upload(
    body: JobCreateRequest,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> JobCreateResponse:
    return await service.initiate_job_upload(current_user["sub"], body)


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    cursor: Optional[str] = None,
    limit: int = Query(default=20, le=100),
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> JobListResponse:
    return await service.list_jobs(current_user["sub"], cursor, limit)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> JobStatusResponse:
    return await service.get_job_status(current_user["sub"], job_id)


@router.post("/jobs/{job_id}/confirm", status_code=202)
async def confirm_job_upload(
    job_id: UUID,
    speaker_ids: Optional[list[UUID]] = None,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> None:
    await service.confirm_job_upload(current_user["sub"], job_id, speaker_ids)


@router.post("/jobs/{job_id}/rerun", status_code=202, response_model=JobStatusResponse)
async def rerun_job(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> JobStatusResponse:
    return await service.rerun_job(current_user["sub"], job_id)


@router.get("/jobs/{job_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> TranscriptResponse:
    return await service.get_transcript(current_user["sub"], job_id)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> None:
    await service.delete_job(current_user["sub"], job_id)


@router.patch("/jobs/{job_id}", response_model=JobStatusResponse)
async def set_job_visibility(
    job_id: UUID,
    body: VisibilityRequest,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> JobStatusResponse:
    return await service.set_visibility(current_user["sub"], job_id, body.is_public)


@router.get("/jobs/{job_id}/turn-distances", response_model=TurnDistancesResponse)
async def get_turn_distances(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> TurnDistancesResponse:
    return await service.get_turn_distances(current_user["sub"], job_id)


@router.get("/jobs/{job_id}/events", response_model=List[JobEventResponse])
async def get_job_events(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> List[JobEventResponse]:
    return await service.get_job_events(current_user["sub"], job_id)


@router.get("/jobs/{job_id}/events/stream")
async def stream_job_events(
    job_id: UUID,
    token: str = Query(..., description="Cognito id_token (EventSource cannot send headers)"),
) -> StreamingResponse:
    payload = await verify_cognito_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user_id: str = payload["sub"]

    async def generator():
        _terminal = {"complete", "failed"}
        last_id = 0

        while True:
            async with db_session.AsyncSessionLocal() as session:
                repo = TranscriptionRepository(session)
                job = await repo.get_job(job_id, user_id)
                if job is None:
                    yield f"event: error\ndata: {json.dumps({'detail': 'Not found'})}\n\n"
                    return

                events = await repo.get_events(job_id, after_id=last_id)
                for ev in events:
                    last_id = ev.id
                    yield (
                        f"data: {json.dumps({'id': ev.id, 'event': ev.event, 'source': ev.source, 'occurred_at': ev.occurred_at.isoformat(), 'detail': ev.detail})}\n\n"
                    )

                if job.status in _terminal:
                    yield f"event: done\ndata: {json.dumps({'status': job.status})}\n\n"
                    return

            await asyncio.sleep(2)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
