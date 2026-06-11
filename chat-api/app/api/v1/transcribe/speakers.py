from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.transcribe.deps import get_transcription_service
from app.dependencies import get_current_user
from app.schemas.transcription import (
    SampleResponse,
    SampleUploadInitResponse,
    SpeakerCreateRequest,
    SpeakerListResponse,
    SpeakerRenameRequest,
    SpeakerResponse,
)
from app.services.transcription_service import TranscriptionService

router = APIRouter()


@router.post("/speakers", status_code=202, response_model=SpeakerResponse)
async def create_speaker(
    body: SpeakerCreateRequest,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> SpeakerResponse:
    return await service.create_speaker(current_user["sub"], body.speaker_name)


@router.get("/speakers", response_model=SpeakerListResponse)
async def list_speakers(
    cursor: Optional[str] = None,
    limit: int = Query(default=20, le=100),
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> SpeakerListResponse:
    return await service.list_speakers(current_user["sub"], cursor, limit)


@router.get("/speakers/{speaker_id}", response_model=SpeakerResponse)
async def get_speaker(
    speaker_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> SpeakerResponse:
    return await service.get_speaker(current_user["sub"], speaker_id)


@router.patch("/speakers/{speaker_id}", response_model=SpeakerResponse)
async def rename_speaker(
    speaker_id: UUID,
    body: SpeakerRenameRequest,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> SpeakerResponse:
    return await service.rename_speaker(current_user["sub"], speaker_id, body.speaker_name)


@router.delete("/speakers/{speaker_id}", status_code=204)
async def delete_speaker(
    speaker_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> None:
    await service.delete_speaker(current_user["sub"], speaker_id)


@router.post("/speakers/{speaker_id}/samples", status_code=202, response_model=SampleUploadInitResponse)
async def initiate_sample_upload(
    speaker_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> SampleUploadInitResponse:
    return await service.initiate_sample_upload(current_user["sub"], speaker_id)


@router.post(
    "/speakers/{speaker_id}/samples/{sample_id}/confirm",
    status_code=202,
    response_model=SampleResponse,
)
async def confirm_sample_upload(
    speaker_id: UUID,
    sample_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> SampleResponse:
    return await service.confirm_sample_upload(current_user["sub"], speaker_id, sample_id)


@router.delete("/speakers/{speaker_id}/samples/{sample_id}", status_code=204)
async def delete_sample(
    speaker_id: UUID,
    sample_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> None:
    await service.delete_sample(current_user["sub"], speaker_id, sample_id)
