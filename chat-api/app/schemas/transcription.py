from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Speaker Profiles ──────────────────────────────────────────────────────────

class SpeakerCreateRequest(BaseModel):
    speaker_name: str = Field(..., min_length=1, max_length=200)


class SpeakerRenameRequest(BaseModel):
    speaker_name: str = Field(..., min_length=1, max_length=200)


# ── Speaker Samples ───────────────────────────────────────────────────────────

class SampleUploadInitResponse(BaseModel):
    sample_id: UUID
    upload_url: str


class SampleResponse(BaseModel):
    sample_id: UUID
    status: str   # processing | ready | failed
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SpeakerResponse(BaseModel):
    speaker_id: UUID
    speaker_name: str
    created_at: datetime
    samples: List[SampleResponse] = []

    model_config = {"from_attributes": True}


class SpeakerListResponse(BaseModel):
    items: List[SpeakerResponse]
    next_cursor: Optional[str] = None


# ── Transcription Jobs ────────────────────────────────────────────────────────

class JobCreateRequest(BaseModel):
    speaker_count_hint: Optional[int] = Field(
        default=None,
        ge=1,
        le=30,
        description="Only set if you are confident in the number of speakers. When omitted, the maximum allowed by the transcription service is used.",
    )
    speaker_ids: Optional[List[UUID]] = None
    language: str = Field(default="en-US", max_length=20)


class JobCreateResponse(BaseModel):
    job_id: UUID
    upload_url: str


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    speaker_count_hint: Optional[int]
    language: str
    speaker_ids: List[UUID] = []
    error_message: Optional[str] = None
    partial_transcript_available: bool = False
    matched_speaker_count: Optional[int] = None
    total_segment_count: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    worker_state: Optional[str] = None         # off | starting | running; None when the GPU controller is disabled
    estimated_wait_seconds: Optional[int] = None
    gpu_notice: Optional[str] = None
    is_public: bool = False

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    items: List[JobStatusResponse]
    next_cursor: Optional[str] = None


class AudioUrlResponse(BaseModel):
    """Presigned playback + download URLs for a job's input audio, or a speaker sample."""
    url: str                # plain GET — what <audio controls> plays
    download_url: str       # same object, Content-Disposition: attachment
    filename: str
    expires_at: datetime


# ── Transcript ────────────────────────────────────────────────────────────────

class SegmentResponse(BaseModel):
    segment_id: UUID
    anonymous_label: str
    speaker_name: Optional[str] = None   # None if unmatched
    start_time: float
    end_time: float
    text: str

    model_config = {"from_attributes": True}


class TranscriptResponse(BaseModel):
    segments: List[SegmentResponse]


# ── Job Events ────────────────────────────────────────────────────────────────

class JobEventResponse(BaseModel):
    id: int
    job_id: UUID
    occurred_at: datetime
    source: str
    event: str
    detail: Optional[dict] = None

    model_config = {"from_attributes": True}


# ── Turn Distances ────────────────────────────────────────────────────────

class TurnCandidateResponse(BaseModel):
    candidate_id: UUID
    speaker_name: Optional[str]
    cosine_dist: float


class TurnDistanceResponse(BaseModel):
    start_time: float
    end_time: float
    text: str
    candidates: List[TurnCandidateResponse]


class TurnDistancesResponse(BaseModel):
    turns: List[TurnDistanceResponse]


# ── Sample Job ────────────────────────────────────────────────────────────────

class SampleJobResponse(BaseModel):
    job_id: UUID
    speaker_ids: List[UUID]


class SampleAudioItem(BaseModel):
    filename: str
    url: str


class SampleSpeakerItem(BaseModel):
    speaker_name: str
    url: str


class SamplePreviewResponse(BaseModel):
    name: str
    audio: SampleAudioItem
    speakers: List[SampleSpeakerItem]
