# Audio Transcription — chat-api Implementation Spec

**Based on:** `audio_transcription_spec.md` v1.1
**Project:** `chat-api/` (FastAPI, Python, PostgreSQL, AWS)
**Status:** Draft

---

## Overview

This document specifies every file to create or modify in `chat-api/` to implement the audio transcription and speaker diarization feature, plus the separate GPU worker (ECS, EC2 launch type). It follows the existing layered architecture: **router → endpoint → service → repository/external service**.

A companion directory `transcription-worker/` is introduced alongside `chat-api/` for the ML-heavy GPU worker, keeping PyTorch out of the main API image.

---

## Workspace Changes

```
/var/www/chat/
  chat-api/               ← existing; add transcription routes + models
  chat-vue/               ← existing; separate spec
  transcription-worker/   ← new; separate Docker image for the GPU worker (ECS, EC2 launch type)
  docs/transcribe/
```

---

## chat-api Changes

### 1. Dependencies

Add to `chat-api/pyproject.toml`:

```toml
"pgvector>=0.3"
"pydub>=0.25"
# boto3 already present; confirm s3, sqs, transcribe clients are used
```

`ffmpeg` must be installed in the Docker image (add `RUN apt-get install -y ffmpeg` to `chat-api/Dockerfile`). It is only used at sample-confirm time to validate audio duration via pydub — it does not run during normal request handling.

### 2. Config (`app/config.py`)

Add to the `Settings` class:

```python
AUDIO_BUCKET_NAME: str
TRANSCRIBE_SQS_QUEUE_URL: str
MAX_CONCURRENT_JOBS: int = 3
```

Add these to `.env.example` with placeholder values.

### 3. Database Models (`app/models/transcription.py`)

New file. All models inherit from `app/models/base.py` (same pattern as existing models). Use `pgvector.sqlalchemy.Vector` for the embedding column.

```python
# app/models/transcription.py

import uuid
from datetime import datetime
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column, String, Float, Integer, ForeignKey,
    DateTime, Text, Enum as SAEnum
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.models.base import Base


class SpeakerProfile(Base):
    __tablename__ = "speaker_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)   # Cognito sub
    speaker_name = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    samples = relationship(
        "SpeakerSample",
        back_populates="speaker_profile",
        cascade="all, delete-orphan",
    )


class SpeakerSample(Base):
    __tablename__ = "speaker_samples"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    speaker_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("speaker_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    s3_key = Column(String(1024), nullable=False)
    duration_seconds = Column(Float, nullable=True)
    status = Column(
        SAEnum("processing", "ready", "failed", name="sample_status"),
        nullable=False,
        default="processing",
    )
    embedding = Column(Vector(256), nullable=True)   # NULL until worker completes
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    speaker_profile = relationship("SpeakerProfile", back_populates="samples")


class TranscriptionJob(Base):
    __tablename__ = "transcription_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    audio_s3_key = Column(String(1024), nullable=False)
    aws_transcribe_job_name = Column(String(256), nullable=True)
    status = Column(
        SAEnum(
            "pending", "transcribing", "matching", "complete", "failed",
            name="job_status",
        ),
        nullable=False,
        default="pending",
    )
    speaker_count_hint = Column(Integer, nullable=False, default=2)
    language = Column(String(20), nullable=False, default="en-US")
    transcribe_output_s3_key = Column(String(1024), nullable=True)
    result_s3_key = Column(String(1024), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    segments = relationship(
        "TranscriptSegment",
        back_populates="job",
        cascade="all, delete-orphan",
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("transcription_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    speaker_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("speaker_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    anonymous_label = Column(String(50), nullable=False)   # always set, e.g. "spk_0"
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(Text, nullable=False)

    job = relationship("TranscriptionJob", back_populates="segments")
    speaker_profile = relationship("SpeakerProfile")

    __table_args__ = (
        # Required for ordered retrieval without full table scan
        Index("ix_transcript_segments_job_start", "job_id", "start_time"),
    )
```

Import these models in `app/models/__init__.py` so Alembic autogenerate picks them up.

### 4. Alembic Migration

Generate with:

```bash
uv run alembic -c app/db/alembic.ini revision --autogenerate -m "add transcription tables"
```

Then **manually edit** the generated migration to prepend the pgvector extension and the ivfflat index:

```python
# In the upgrade() function, before create_table calls:
op.execute("CREATE EXTENSION IF NOT EXISTS vector")

# After the speaker_samples table is created:
op.execute(
    "CREATE INDEX ix_speaker_samples_embedding "
    "ON speaker_samples USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
)
```

The `lists = 100` is a reasonable starting value for < 10k embeddings. The downgrade should `DROP EXTENSION vector CASCADE` (which also drops the index and column).

### 5. Pydantic Schemas (`app/schemas/transcription.py`)

```python
# app/schemas/transcription.py

from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


# ── Speaker Profiles ────────────────────────────────────────────────────────

class SpeakerCreateRequest(BaseModel):
    speaker_name: str = Field(..., min_length=1, max_length=200)


class SpeakerResponse(BaseModel):
    speaker_id: UUID
    speaker_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SpeakerListResponse(BaseModel):
    items: List[SpeakerResponse]
    next_cursor: Optional[str] = None


# ── Speaker Samples ──────────────────────────────────────────────────────────

class SampleUploadInitResponse(BaseModel):
    sample_id: UUID
    upload_url: str


class SampleResponse(BaseModel):
    sample_id: UUID
    status: str   # processing | ready | failed
    duration_seconds: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Transcription Jobs ───────────────────────────────────────────────────────

class JobCreateRequest(BaseModel):
    speaker_count_hint: int = Field(default=2, ge=2, le=30)
    speaker_ids: Optional[List[UUID]] = None
    language: str = Field(default="en-US", max_length=20)


class JobCreateResponse(BaseModel):
    job_id: UUID
    upload_url: str


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    speaker_count_hint: int
    language: str
    error_message: Optional[str] = None
    partial_transcript_available: bool = False
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    items: List[JobStatusResponse]
    next_cursor: Optional[str] = None


# ── Transcript ───────────────────────────────────────────────────────────────

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
    transcript_url: Optional[str] = None   # pre-signed S3 GET URL; None when partial
```

### 6. Repository (`app/repositories/transcription.py`)

Async SQLAlchemy only — no business logic.

```python
# app/repositories/transcription.py

from uuid import UUID
from typing import List, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.transcription import (
    SpeakerProfile, SpeakerSample, TranscriptionJob, TranscriptSegment
)


class TranscriptionRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Speaker Profiles ─────────────────────────────────────────────────────

    async def create_speaker(self, user_id: str, name: str) -> SpeakerProfile:
        ...

    async def get_speaker(self, speaker_id: UUID, user_id: str) -> Optional[SpeakerProfile]:
        """Returns None if not found or not owned by user_id."""
        ...

    async def list_speakers(
        self, user_id: str, cursor: Optional[str], limit: int
    ) -> tuple[List[SpeakerProfile], Optional[str]]:
        """Cursor-paginated by (created_at, id). Returns (items, next_cursor)."""
        ...

    async def delete_speaker(self, speaker_id: UUID) -> None:
        """Cascade deletes samples. Sets transcript_segments.speaker_profile_id = NULL via DB constraint."""
        ...

    # ── Speaker Samples ──────────────────────────────────────────────────────

    async def create_sample(
        self, speaker_profile_id: UUID, s3_key: str
    ) -> SpeakerSample:
        ...

    async def get_sample(
        self, sample_id: UUID, speaker_profile_id: UUID
    ) -> Optional[SpeakerSample]:
        ...

    async def update_sample_status(
        self,
        sample_id: UUID,
        status: str,
        duration_seconds: Optional[float] = None,
    ) -> None:
        ...

    async def delete_sample(self, sample_id: UUID) -> None:
        ...

    # ── Transcription Jobs ───────────────────────────────────────────────────

    async def create_job(
        self,
        user_id: str,
        audio_s3_key: str,
        speaker_count_hint: int,
        language: str,
    ) -> TranscriptionJob:
        ...

    async def get_job(self, job_id: UUID, user_id: str) -> Optional[TranscriptionJob]:
        ...

    async def count_active_jobs(self, user_id: str) -> int:
        """Count jobs with status in ('pending', 'transcribing', 'matching')."""
        ...

    async def update_job_status(
        self,
        job_id: UUID,
        status: str,
        aws_transcribe_job_name: Optional[str] = None,
        transcribe_output_s3_key: Optional[str] = None,
        result_s3_key: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        ...

    async def list_jobs(
        self, user_id: str, cursor: Optional[str], limit: int
    ) -> tuple[List[TranscriptionJob], Optional[str]]:
        ...

    async def delete_job(self, job_id: UUID) -> None:
        ...

    # ── Transcript Segments ──────────────────────────────────────────────────

    async def get_segments(self, job_id: UUID) -> List[TranscriptSegment]:
        """Returns segments ordered by start_time."""
        ...
```

**Cursor pagination pattern:** encode cursor as `base64(json({"created_at": ..., "id": ...}))`. The list query adds `WHERE (created_at, id) < (cursor_created_at, cursor_id) ORDER BY created_at DESC, id DESC LIMIT limit+1`. If `len(results) > limit`, pop the last item and encode it as `next_cursor`.

### 7. Service Layer

#### `app/services/audio_storage.py`

Handles all S3 and AWS Transcribe interactions. Keeps boto3 calls out of the router.

```python
class AudioStorageService:

    def __init__(self, settings):
        self.s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        self.bucket = settings.AUDIO_BUCKET_NAME

    def generate_presigned_upload_url(
        self,
        s3_key: str,
        ttl_seconds: int = 900,
        max_size_bytes: int = 2 * 1024 ** 3,
    ) -> str:
        """
        Returns a pre-signed POST URL dict (url + fields).
        Conditions: content-type audio/*, content-length-range 1–max_size_bytes.
        TTL: 15 minutes.
        """
        ...

    def generate_presigned_download_url(self, s3_key: str, ttl_seconds: int = 3600) -> str:
        """Returns a pre-signed GET URL. TTL: 60 minutes."""
        ...

    def object_exists(self, s3_key: str) -> bool:
        """head_object; returns False on 404."""
        ...

    def get_object_bytes(self, s3_key: str) -> bytes:
        """Downloads S3 object into memory. Used for pydub duration check."""
        ...

    def delete_objects(self, s3_keys: list[str]) -> None:
        """delete_objects (batch). Silently ignores missing keys."""
        ...
```

#### `app/services/transcription_service.py`

Business logic for jobs and speakers. Injected with `AudioStorageService`, `SQSPublisher`, `TranscriptionRepository`.

Key methods and their logic:

**`initiate_job_upload(user_id, request) → JobCreateResponse`**
1. `repo.count_active_jobs(user_id)` → raise `429` if ≥ `MAX_CONCURRENT_JOBS`
2. Compute `s3_key = f"audio/{user_id}/{job_id}/source.{ext}"` (ext = generic, extension resolved at confirm time)
3. `repo.create_job(...)` with `status = pending`
4. `storage.generate_presigned_upload_url(s3_key)` → return `{ job_id, upload_url }`

**`confirm_job_upload(user_id, job_id) → None`**
1. `repo.get_job(job_id, user_id)` → 404 if missing
2. Guard: only `pending` jobs can be confirmed (409 otherwise)
3. `storage.object_exists(s3_key)` → 422 if missing
4. `transcribe_client.start_job(...)` → get `aws_transcribe_job_name`
5. `sqs.publish_transcription_job(job_id, aws_transcribe_job_name, speaker_ids)`
6. `repo.update_job_status(job_id, "transcribing", aws_transcribe_job_name=...)`

**`get_transcript(user_id, job_id) → TranscriptResponse`**
1. Get job → 404 if missing
2. If status in `(pending, transcribing, matching)` → raise `409`
3. If `complete`: load segments from DB, generate pre-signed URL for `result_s3_key`, return full response
4. If `failed` and `transcribe_output_s3_key` set: load segments (anonymous labels only), return without `transcript_url`
5. If `failed` without partial data: raise `409` with `"no transcript available"`

**`delete_job(user_id, job_id) → None`**
1. Get job → 404 if missing
2. Collect all S3 keys: `audio_s3_key`, `transcribe_output_s3_key`, `result_s3_key`, plus `segments/*` prefix listing
3. `storage.delete_objects([...])`, then `repo.delete_job(job_id)` (cascades segments)

**Speaker methods:** `create_speaker`, `list_speakers`, `delete_speaker` (with S3 cleanup of all sample keys), `initiate_sample_upload`, `confirm_sample_upload`, `delete_sample`.

**`confirm_sample_upload`** must:
1. Download bytes from S3 via `storage.get_object_bytes(s3_key)`
2. Parse with pydub: `AudioSegment.from_file(io.BytesIO(data))` → catch `CouldntDecodeError` → 422 `unsupported_format`
3. Check `duration_seconds < 10` → 422 `duration_too_short`
4. Check `duration_seconds > 60` → 422 `duration_too_long`
5. `repo.update_sample_status(sample_id, "processing", duration_seconds=duration_seconds)`
6. `sqs.publish_sample_embedding(sample_id, s3_key)`

#### `app/services/sqs_publisher.py`

```python
import json, boto3
from uuid import UUID

class SQSPublisher:
    def __init__(self, queue_url: str, region: str):
        self.sqs = boto3.client("sqs", region_name=region)
        self.queue_url = queue_url

    def publish_transcription_job(
        self, job_id: UUID, aws_job_name: str, speaker_ids: list[UUID] | None
    ) -> None:
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps({
                "type": "transcription_job",
                "job_id": str(job_id),
                "aws_transcribe_job_name": aws_job_name,
                "speaker_ids": [str(s) for s in speaker_ids] if speaker_ids else None,
            }),
        )

    def publish_sample_embedding(self, sample_id: UUID, s3_key: str) -> None:
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps({
                "type": "sample_embedding",
                "sample_id": str(sample_id),
                "s3_key": s3_key,
            }),
        )
```

### 8. API Router

Create `app/api/v1/transcribe/` as a sub-package:

```
app/api/v1/transcribe/
  __init__.py   # exports router
  speakers.py
  jobs.py
```

Register in `app/api/v1/__init__.py`:

```python
from app.api.v1.transcribe import router as transcribe_router
v1_router.include_router(transcribe_router, prefix="/transcribe", tags=["transcribe"])
```

#### `app/api/v1/transcribe/speakers.py` — selected endpoints

```python
router = APIRouter()

@router.post("/speakers", status_code=202)
async def create_speaker(
    body: SpeakerCreateRequest,
    user: CognitoUser = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> SpeakerResponse:
    return await service.create_speaker(user.sub, body.speaker_name)


@router.get("/speakers")
async def list_speakers(
    cursor: Optional[str] = None,
    limit: int = Query(default=20, le=100),
    user: CognitoUser = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> SpeakerListResponse:
    return await service.list_speakers(user.sub, cursor, limit)


@router.delete("/speakers/{speaker_id}", status_code=204)
async def delete_speaker(
    speaker_id: UUID,
    user: CognitoUser = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> None:
    await service.delete_speaker(user.sub, speaker_id)


@router.post("/speakers/{speaker_id}/samples", status_code=202)
async def initiate_sample_upload(
    speaker_id: UUID,
    user: CognitoUser = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> SampleUploadInitResponse:
    return await service.initiate_sample_upload(user.sub, speaker_id)


@router.post("/speakers/{speaker_id}/samples/{sample_id}/confirm", status_code=202)
async def confirm_sample_upload(
    speaker_id: UUID,
    sample_id: UUID,
    user: CognitoUser = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> SampleResponse:
    return await service.confirm_sample_upload(user.sub, speaker_id, sample_id)


@router.delete("/speakers/{speaker_id}/samples/{sample_id}", status_code=204)
async def delete_sample(
    speaker_id: UUID,
    sample_id: UUID,
    user: CognitoUser = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> None:
    await service.delete_sample(user.sub, speaker_id, sample_id)
```

#### `app/api/v1/transcribe/jobs.py`

Same pattern — one handler per endpoint from the spec. All path parameters validated for ownership via `service.get_job(user.sub, job_id)` returning 404 if not found or not owned.

The `GET /jobs/{job_id}/transcript` endpoint returns `409` when status is `pending | transcribing | matching` via a custom `HTTPException`.

#### Dependency injection — `app/api/v1/transcribe/__init__.py`

```python
from functools import lru_cache
from app.config import get_settings
from app.services.transcription_service import TranscriptionService
from app.services.audio_storage import AudioStorageService
from app.services.sqs_publisher import SQSPublisher

def get_transcription_service(db: AsyncSession = Depends(get_db)) -> TranscriptionService:
    settings = get_settings()
    storage = AudioStorageService(settings)
    sqs = SQSPublisher(settings.TRANSCRIBE_SQS_QUEUE_URL, settings.AWS_REGION)
    repo = TranscriptionRepository(db)
    return TranscriptionService(repo, storage, sqs)
```

### 9. Exception Handling

Add to `app/core/exceptions.py`:

```python
class ConcurrentJobLimitExceeded(AppException):
    status_code = 429
    detail = "Maximum concurrent jobs reached"

class AudioUploadMissing(AppException):
    status_code = 422
    detail = "Audio file not found at expected S3 location"

class AudioValidationError(AppException):
    """Raised with an error_code field: duration_too_short | duration_too_long | unsupported_format"""
    status_code = 422
```

Register in `app/main.py` the same way existing exceptions are registered.

### 10. Unit Tests

Add under `tests/unit/services/`:

- `test_transcription_service.py` — mock `AudioStorageService`, `SQSPublisher`, `TranscriptionRepository`; test job lifecycle, concurrent limit, status transitions, transcript retrieval cases
- `test_sample_validation.py` — mock pydub; test all three 422 cases (too short, too long, unsupported format)

Add under `tests/unit/api/`:

- `test_transcribe_speakers.py` — test ownership 404 enforcement, 202 responses
- `test_transcribe_jobs.py` — test 429 limit, 409 status guard, partial transcript flag

---

## transcription-worker Service

New top-level directory `transcription-worker/` alongside `chat-api/`. **Separate Docker image** — ~2.5 GB due to PyTorch/SpeechBrain.

### Directory Structure

```
transcription-worker/
  Dockerfile
  pyproject.toml          # or requirements.txt
  main.py                 # entry point: SQS poll loop
  config.py               # Settings
  db.py                   # SQLAlchemy engine + session (mirrors chat-api)
  models.py               # Duplicated SQLAlchemy models (deployment independence)
  handlers/
    transcription.py      # process_transcription_job()
    embedding.py          # process_sample_embedding()
  services/
    embedder.py           # ECAPA-TDNN via SpeechBrain
    matcher.py            # cosine similarity via pgvector
    s3_client.py          # download/upload audio, delete segments
    transcribe_poller.py  # poll AWS Transcribe, parse diarized JSON
```

### `config.py`

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    AUDIO_BUCKET_NAME: str
    TRANSCRIBE_SQS_QUEUE_URL: str
    AWS_REGION: str = "us-east-1"
    SQS_VISIBILITY_EXTENSION_INTERVAL: int = 300  # seconds
    SQS_VISIBILITY_TIMEOUT: int = 600
    MATCHING_THRESHOLD: float = 0.25  # cosine distance
    SPEECHBRAIN_CHECKPOINT: str = "speechbrain/spkrec-ecapa-voxceleb"
    SPEECHBRAIN_REVISION: str = "3c54e95"
```

### `main.py` — SQS Poll Loop

```python
import json, signal, time, threading
import boto3
from config import Settings
from handlers.transcription import process_transcription_job
from handlers.embedding import process_sample_embedding

settings = Settings()
sqs = boto3.client("sqs", region_name=settings.AWS_REGION)

HANDLERS = {
    "transcription_job": process_transcription_job,
    "sample_embedding": process_sample_embedding,
}

def extend_visibility(receipt_handle: str, stop_event: threading.Event) -> None:
    """Background thread: calls ChangeMessageVisibility every 5 minutes."""
    while not stop_event.wait(settings.SQS_VISIBILITY_EXTENSION_INTERVAL):
        sqs.change_message_visibility(
            QueueUrl=settings.TRANSCRIBE_SQS_QUEUE_URL,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=settings.SQS_VISIBILITY_TIMEOUT,
        )

def process_message(message: dict) -> None:
    body = json.loads(message["Body"])
    msg_type = body.get("type")
    handler = HANDLERS.get(msg_type)
    if not handler:
        raise ValueError(f"Unknown message type: {msg_type}")

    stop_event = threading.Event()
    extender = threading.Thread(
        target=extend_visibility,
        args=(message["ReceiptHandle"], stop_event),
        daemon=True,
    )
    extender.start()
    try:
        handler(body, settings)
        sqs.delete_message(
            QueueUrl=settings.TRANSCRIBE_SQS_QUEUE_URL,
            ReceiptHandle=message["ReceiptHandle"],
        )
    finally:
        stop_event.set()

def run():
    while True:
        resp = sqs.receive_message(
            QueueUrl=settings.TRANSCRIBE_SQS_QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
        )
        for msg in resp.get("Messages", []):
            process_message(msg)
```

### `handlers/transcription.py`

```
process_transcription_job(body, settings):
1. Update job status → "matching" (it arrives as "transcribing")
2. Poll AWS Transcribe (loop with 30-s sleep):
   - GetTranscriptionJob until status IN (COMPLETED, FAILED)
3. On FAILED: update job → failed, error_message = "transcribing: AWS Transcribe failed"
4. Download transcript JSON from TranscriptionJobOutput.TranscriptFileUri → S3
5. Parse items[] from diarized JSON to extract segments per speaker label
6. For each unique speaker label (spk_0, spk_1, ...):
   a. Extract audio slice from source audio using pydub
   b. Save temp WAV to S3 at segments/{label}.wav
   c. Generate 256-dim ECAPA-TDNN embedding via embedder.encode(wav_bytes)
7. Load ready speaker_samples for user; perform cosine similarity matching
8. For each segment: resolve label → speaker_profile_id (if distance ≤ 0.25)
9. Write transcript_segments rows to DB
10. Write transcript.txt to S3 (annotated format per spec)
11. Delete segments/*.wav from S3
12. Update job → complete, result_s3_key = "audio/{user_id}/{job_id}/transcript.txt"
```

Error handling: any exception in steps 4–12 catches, updates job to `failed` with `error_message = "{step}: {exception summary}"`, then re-raises (so SQS message is not deleted and retries up to maxReceiveCount=3 before DLQ).

### `handlers/embedding.py`

```
process_sample_embedding(body, settings):
1. Download sample audio from S3
2. Generate 256-dim ECAPA-TDNN embedding via embedder.encode(wav_bytes)
3. UPDATE speaker_samples SET embedding = ..., status = 'ready' WHERE id = sample_id
4. On error: UPDATE speaker_samples SET status = 'failed'
```

### `services/embedder.py`

```python
from speechbrain.pretrained import EncoderClassifier

class EcapaTdnnEmbedder:
    _instance = None

    @classmethod
    def get(cls) -> "EcapaTdnnEmbedder":
        """Singleton — model loaded once at worker startup."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.model = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            revision="3c54e95",
            savedir="/tmp/speechbrain",
        )

    def encode(self, wav_bytes: bytes) -> list[float]:
        """Returns a 256-element float list (L2-normalised embedding)."""
        # write bytes to temp file, load with torchaudio, run model.encode_batch()
        ...
```

### `services/matcher.py`

```python
from scipy.spatial.distance import cosine

def match_speaker(
    segment_embedding: list[float],
    candidate_samples: list[dict],  # each: {speaker_profile_id, embedding}
    threshold: float = 0.25,
) -> str | None:
    """
    Returns speaker_profile_id of closest match if cosine distance ≤ threshold,
    else None. Uses per-speaker average of all ready sample embeddings.
    """
    best_id, best_dist = None, float("inf")
    for sample in candidate_samples:
        dist = cosine(segment_embedding, sample["embedding"])
        if dist < best_dist:
            best_dist, best_id = dist, sample["speaker_profile_id"]
    return best_id if best_dist <= threshold else None
```

### Dockerfile (worker)

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir speechbrain pydub boto3 pydantic-settings pgvector asyncpg sqlalchemy scipy

# Pre-download model checkpoint at build time (pins to commit 3c54e95)
RUN python -c "
from speechbrain.pretrained import EncoderClassifier
EncoderClassifier.from_hparams(
    source='speechbrain/spkrec-ecapa-voxceleb',
    revision='3c54e95',
    savedir='/app/speechbrain_model',
)
"
COPY . .
ENV SPEECHBRAIN_CACHE=/app/speechbrain_model
CMD ["python", "main.py"]
```

---

## CloudWatch Metrics (Worker)

The worker should emit these custom metrics after each job:

```python
cloudwatch.put_metric_data(
    Namespace="TranscriptionWorker",
    MetricData=[
        {"MetricName": "TranscriptionJobDuration", "Value": elapsed_seconds, "Unit": "Seconds"},
        {"MetricName": "SpeakerMatchSuccessRate", "Value": matched_pct, "Unit": "Percent"},
    ],
)
```

And use a structured log format so the `WorkerErrorRate` filter (`ERROR` keyword) works correctly.

---

## New Environment Variables Summary

| Variable | Service | Description |
|---|---|---|
| `AUDIO_BUCKET_NAME` | chat-api, worker | S3 bucket for audio files |
| `TRANSCRIBE_SQS_QUEUE_URL` | chat-api, worker | SQS queue URL |
| `MAX_CONCURRENT_JOBS` | chat-api | Default 3 |
| `DATABASE_URL` | worker | Same RDS instance |
| `AWS_REGION` | worker | |
| `MATCHING_THRESHOLD` | worker | Default 0.25 |

---

## Implementation Order

1. Alembic migration + models
2. Schemas
3. Repository
4. `AudioStorageService` + `SQSPublisher` (no AWS in tests; mock with moto or unittest.mock)
5. `TranscriptionService`
6. Routers
7. Wire into `app/main.py`
8. Unit tests
9. Worker: `embedder.py` → `matcher.py` → `transcription.py` handler → `embedding.py` handler → `main.py`
