"""Unauthenticated read-only routes. Serves only rows flagged is_public;
everything else — including rows that exist but are private — is a 404."""
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.public.deps import get_public_service
from app.schemas.public import (
    PublicConversationDetail,
    PublicScanDetail,
    PublicTranscriptionDetail,
    ShowcaseResponse,
)
from app.services.public_service import PublicService

router = APIRouter()


@router.get("/showcase", response_model=ShowcaseResponse)
async def showcase(service: PublicService = Depends(get_public_service)) -> ShowcaseResponse:
    return await service.showcase()


@router.get("/photogrammetry/{job_id}", response_model=PublicScanDetail)
async def scan_detail(
    job_id: UUID, service: PublicService = Depends(get_public_service)
) -> PublicScanDetail:
    return await service.scan_detail(job_id)


@router.get("/transcriptions/{job_id}", response_model=PublicTranscriptionDetail)
async def transcription_detail(
    job_id: UUID, service: PublicService = Depends(get_public_service)
) -> PublicTranscriptionDetail:
    return await service.transcription_detail(job_id)


@router.get("/conversations/{conversation_id}", response_model=PublicConversationDetail)
async def conversation_detail(
    conversation_id: UUID, service: PublicService = Depends(get_public_service)
) -> PublicConversationDetail:
    return await service.conversation_detail(conversation_id)
