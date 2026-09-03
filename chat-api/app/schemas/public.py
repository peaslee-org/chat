"""Schemas served by the unauthenticated /api/v1/public router.

Everything here is visible to anyone on the internet: no user identifiers,
S3 keys, cost fields, or error internals — guarded by test_public_schemas.py.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.transcription import CompiledTurn, CompileSettings, SegmentResponse


class VisibilityRequest(BaseModel):
    is_public: bool


class PublicScanSummary(BaseModel):
    job_id: UUID
    name: str
    image_count: int
    status: str
    preview_url: Optional[str] = None
    created_at: datetime


class PublicScanDetail(PublicScanSummary):
    warnings: List[str] = Field(default_factory=list)
    matched: Optional[int] = None  # photos SfM registered, from photo_status
    total: Optional[int] = None
    mesh_url: Optional[str] = None  # presigned GET; only when status == complete
    expires_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class PublicTranscriptionSummary(BaseModel):
    job_id: UUID
    created_at: datetime
    duration_seconds: Optional[float] = None  # max segment end_time
    segment_count: Optional[int] = None
    speaker_count: Optional[int] = None


class PublicTranscriptionDetail(PublicTranscriptionSummary):
    segments: List[SegmentResponse] = Field(default_factory=list)
    turns: Optional[List[CompiledTurn]] = None
    settings: CompileSettings = Field(default_factory=CompileSettings)
    compiled_at: Optional[datetime] = None


class PublicMessage(BaseModel):
    role: str
    content: str
    created_at: datetime


class PublicConversationSummary(BaseModel):
    conversation_id: UUID
    title: Optional[str] = None
    model_id: Optional[str] = None
    created_at: datetime


class PublicConversationDetail(PublicConversationSummary):
    messages: List[PublicMessage] = Field(default_factory=list)


class ShowcaseResponse(BaseModel):
    scans: List[PublicScanSummary] = Field(default_factory=list)
    transcriptions: List[PublicTranscriptionSummary] = Field(default_factory=list)
    conversations: List[PublicConversationSummary] = Field(default_factory=list)
