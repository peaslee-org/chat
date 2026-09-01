# Public Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A no-login `/demo` page showing owner-flagged (`is_public`) scans, transcripts, and conversations through new unauthenticated read-only `/api/v1/public` endpoints.

**Architecture:** One migration adds `is_public` to three tables. A new `PublicService` (repos + storage, no auth) serves scrubbed schemas through a router mounted without any auth dependency; the three authed routers gain a PATCH to toggle the flag. The SPA gets a `/demo` route (the router guard now sends logged-out visitors there instead of straight to Cognito) reusing the presentational components `MeshViewer`, `TranscriptDisplay`, `MessageList`.

**Tech Stack:** FastAPI + SQLAlchemy (async) + Alembic; Vue 3 + Pinia + vitest.

**Spec:** `docs/superpowers/specs/2026-09-01-aitools-rename-and-public-demo-design.md` (Part 2)

## Global Constraints

- **Scrub rule:** no public schema may carry `user_id`, `user_sub`, `input_prefix`, `mesh_s3_key`, `preview_s3_key`, `audio_s3_key`, `input_price_per_1k_tokens`, `output_price_per_1k_tokens`, or `error_message`. Presigned URLs are values, not keys — they're fine.
- A non-public id and a nonexistent id must be indistinguishable: both raise `NotFoundError` with the same message shape → 404.
- Presigned URL TTL: reuse `DOWNLOAD_TTL_SECONDS = 900` from `app/services/photogrammetry_service.py:48`.
- Backend commands run from `chat-api/`: `uv run pytest tests/unit -q` (CI's suite), `uv run ruff check .`. Frontend from `chat-vue/`: `npm run test`.
- TDD per task: write the failing test, watch it fail, implement, watch it pass, commit.
- Known deviations from the spec's Part 2 wording (approved direction, adjusted to reality): transcription rows have no title — public listings use `created_at` + derived duration; there is no login page — the router guard redirect **is** the demo link.

---

### Task 1: `is_public` columns + migration

**Files:**
- Modify: `chat-api/app/models/conversation.py`, `chat-api/app/models/photogrammetry.py`, `chat-api/app/models/transcription.py`
- Create: `chat-api/app/db/migrations/versions/u1v2w3x4y5z6_add_is_public_flags.py`
- Test: `chat-api/tests/unit/test_is_public_columns.py`

**Interfaces:**
- Produces: `Conversation.is_public`, `TranscriptionJob.is_public`, `PhotogrammetryJob.is_public` — `bool`, not null, defaults False in Python and in the DB. Every later task relies on these attribute names.

- [ ] **Step 1: Write the failing test**

```python
from app.models.conversation import Conversation
from app.models.photogrammetry import PhotogrammetryJob
from app.models.transcription import TranscriptionJob


def test_is_public_columns_exist_not_null_default_false():
    for model in (Conversation, TranscriptionJob, PhotogrammetryJob):
        col = model.__table__.c.is_public
        assert col.nullable is False, model.__name__
        assert col.server_default is not None, model.__name__
```

- [ ] **Step 2: Run it — expect FAIL** (`KeyError: 'is_public'`): `uv run pytest tests/unit/test_is_public_columns.py -q`

- [ ] **Step 3: Add the column to each model**

In each of the three model classes add (models use `Mapped`/`mapped_column`; extend the file's existing `from sqlalchemy import …` line with `Boolean, text`):

```python
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
```

Place it after the last scalar column of each class (`Conversation` after `output_price_per_1k_tokens`; `TranscriptionJob` after `completed_at`/before the `segments` relationship; `PhotogrammetryJob` after `completed_at`).

- [ ] **Step 4: Write the migration** (hand-chained ids; head is `t0u1v2w3x4y5`):

```python
"""add is_public to conversations, transcription_jobs, photogrammetry_jobs (public demo opt-in)

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "u1v2w3x4y5z6"
down_revision: Union[str, None] = "t0u1v2w3x4y5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("conversations", "transcription_jobs", "photogrammetry_jobs")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_column(table, "is_public")
```

- [ ] **Step 5: Verify** — `uv run pytest tests/unit/test_is_public_columns.py -q` passes; `uv run alembic -c app/db/alembic.ini heads` prints exactly `u1v2w3x4y5z6 (head)` (no DB needed).

- [ ] **Step 6: Commit** — `git add` the four files + test; `git commit -m "feat(api): is_public flags on conversations and jobs"`

---

### Task 2: Public schemas

**Files:**
- Create: `chat-api/app/schemas/public.py`
- Test: `chat-api/tests/unit/test_public_schemas.py`

**Interfaces:**
- Consumes: `SegmentResponse` from `app/schemas/transcription.py:96`.
- Produces (exact class/field names Tasks 3-5 and the SPA rely on): `VisibilityRequest{is_public}`, `PublicScanSummary{job_id,name,image_count,status,preview_url,created_at}`, `PublicScanDetail(+warnings,matched,total,mesh_url,expires_at,completed_at)`, `PublicTranscriptionSummary{job_id,created_at,duration_seconds,segment_count,speaker_count}`, `PublicTranscriptionDetail(+segments)`, `PublicMessage{role,content,created_at}`, `PublicConversationSummary{conversation_id,title,model_id,created_at}`, `PublicConversationDetail(+messages)`, `ShowcaseResponse{scans,transcriptions,conversations}`.

- [ ] **Step 1: Write the failing test**

```python
from pydantic import BaseModel

FORBIDDEN = {
    "user_id", "user_sub", "input_prefix", "mesh_s3_key", "preview_s3_key",
    "audio_s3_key", "input_price_per_1k_tokens", "output_price_per_1k_tokens",
    "error_message",
}


def test_public_schemas_never_expose_private_fields():
    import app.schemas.public as public

    checked = 0
    for name in dir(public):
        cls = getattr(public, name)
        if isinstance(cls, type) and issubclass(cls, BaseModel) and cls.__module__ == public.__name__:
            leaked = FORBIDDEN & set(cls.model_fields)
            assert not leaked, f"{name} exposes {leaked}"
            checked += 1
    assert checked >= 9


def test_showcase_shape():
    from app.schemas.public import ShowcaseResponse

    s = ShowcaseResponse()
    assert (s.scans, s.transcriptions, s.conversations) == ([], [], [])
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: app.schemas.public`).

- [ ] **Step 3: Implement `app/schemas/public.py`**

```python
"""Schemas served by the unauthenticated /api/v1/public router.

Everything here is visible to anyone on the internet: no user identifiers,
S3 keys, cost fields, or error internals — guarded by test_public_schemas.py.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.transcription import SegmentResponse


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
```

- [ ] **Step 4: Run — expect PASS.** Then `uv run pytest tests/unit -q` (no regressions).

- [ ] **Step 5: Commit** — `git commit -m "feat(api): public demo schemas with scrub guard"`

---

### Task 3: Repo lookups + PublicService

**Files:**
- Modify: `chat-api/app/repositories/photogrammetry.py`, `chat-api/app/repositories/transcription.py`, `chat-api/app/repositories/conversation.py`
- Create: `chat-api/app/services/public_service.py`
- Test: `chat-api/tests/unit/services/test_public_service.py`

**Interfaces:**
- Consumes: Task 1 columns, Task 2 schemas, `NotFoundError` (`app/core/exceptions.py`), `DOWNLOAD_TTL_SECONDS`, storage's `generate_presigned_download_url(s3_key, ttl_seconds)`.
- Produces — repo methods (each repo keeps its own session-attribute style: `self.db` in photogrammetry, `self._db` in conversation; match transcription's existing attribute):
  - `PhotogrammetryRepository.list_public_jobs(limit: int) -> list[PhotogrammetryJob]`, `.get_public_job(job_id) -> PhotogrammetryJob | None`, `.set_is_public(job_id, user_id, value) -> PhotogrammetryJob | None`
  - `TranscriptionRepository.list_public_jobs(limit)`, `.get_public_job(job_id)`, `.set_is_public(job_id, user_id, value)`, `.get_segment_stats(job_id) -> tuple[float | None, int]`
  - `ConversationRepository.list_public(limit)`, `.get_public(conversation_id) -> Conversation | None`, `.set_is_public(conversation_id, user_sub, value) -> Conversation` (raises NotFound/Forbidden via existing `.get`)
- Produces — `PublicService(scans, transcriptions, conversations, storage)` with `async showcase() -> ShowcaseResponse`, `async scan_detail(job_id) -> PublicScanDetail`, `async transcription_detail(job_id) -> PublicTranscriptionDetail`, `async conversation_detail(conversation_id) -> PublicConversationDetail`.

- [ ] **Step 1: Repo methods** (patterned on the file's existing queries; photogrammetry shown, transcription is identical with its model, conversation uses `user_sub`/`self._db`):

```python
    async def list_public_jobs(self, limit: int = 20) -> list[PhotogrammetryJob]:
        result = await self.db.execute(
            select(PhotogrammetryJob)
            .where(PhotogrammetryJob.is_public.is_(True))
            .order_by(PhotogrammetryJob.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def get_public_job(self, job_id: UUID) -> Optional[PhotogrammetryJob]:
        result = await self.db.execute(
            select(PhotogrammetryJob).where(
                PhotogrammetryJob.id == job_id,
                PhotogrammetryJob.is_public.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def set_is_public(self, job_id: UUID, user_id: str, value: bool) -> Optional[PhotogrammetryJob]:
        job = await self.get_job(job_id, user_id)
        if job is None:
            return None
        job.is_public = value
        await self.db.flush()
        return job
```

Transcription additionally gets:

```python
    async def get_segment_stats(self, job_id: UUID) -> tuple[Optional[float], int]:
        result = await self.db.execute(
            select(func.max(TranscriptSegment.end_time), func.count(TranscriptSegment.id)).where(
                TranscriptSegment.job_id == job_id
            )
        )
        duration, count = result.one()
        return duration, count
```

Conversation (existing `.get` raises `NotFoundError`/`ForbiddenError`, keep that behavior for the toggle; `get_public` must NOT raise Forbidden — a private conversation is a plain `None`):

```python
    async def list_public(self, limit: int = 20) -> list[Conversation]:
        result = await self._db.execute(
            select(Conversation)
            .where(Conversation.is_public.is_(True))
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def get_public(self, conversation_id: UUID) -> Optional[Conversation]:
        result = await self._db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.is_public.is_(True)
            )
        )
        return result.scalar_one_or_none()

    async def set_is_public(self, conversation_id: UUID, user_sub: str, value: bool) -> Conversation:
        conversation = await self.get(conversation_id, user_sub)
        conversation.is_public = value
        await self._db.flush()
        return conversation
```

- [ ] **Step 2: Write the failing service tests** (`AsyncMock` repos, `MagicMock` storage — same style as `tests/unit/services/`):

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.services.public_service import PublicService


def scan(**over):
    d = dict(
        id=uuid4(), name="cat", image_count=22, status="complete",
        preview_s3_key="p.png", mesh_s3_key="m.glb", warnings=["w1"],
        photo_status={"a.jpg": "registered", "b.jpg": "unregistered"},
        created_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
    )
    d.update(over)
    return MagicMock(**d)


def make_service(**repo_returns):
    scans, transcriptions, conversations = AsyncMock(), AsyncMock(), AsyncMock()
    storage = MagicMock()
    storage.generate_presigned_download_url.return_value = "https://signed"
    svc = PublicService(scans, transcriptions, conversations, storage)
    return svc, scans, transcriptions, conversations, storage


async def test_scan_detail_presigns_mesh_only_when_complete():
    svc, scans, *_ = make_service()
    scans.get_public_job.return_value = scan()
    detail = await svc.scan_detail(uuid4())
    assert detail.mesh_url == "https://signed" and detail.matched == 1 and detail.total == 22

    scans.get_public_job.return_value = scan(status="processing", mesh_s3_key=None)
    detail = await svc.scan_detail(uuid4())
    assert detail.mesh_url is None and detail.expires_at is None


async def test_scan_detail_404_when_not_public_or_missing():
    svc, scans, *_ = make_service()
    scans.get_public_job.return_value = None
    with pytest.raises(NotFoundError):
        await svc.scan_detail(uuid4())


async def test_showcase_assembles_all_three_features():
    svc, scans, transcriptions, conversations, _ = make_service()
    scans.list_public_jobs.return_value = [scan()]
    tjob = MagicMock(id=uuid4(), created_at=datetime.now(timezone.utc), matched_speaker_count=2)
    transcriptions.list_public_jobs.return_value = [tjob]
    transcriptions.get_segment_stats.return_value = (123.4, 56)
    conversations.list_public.return_value = [
        MagicMock(id=uuid4(), title="t", model_id="m", created_at=datetime.now(timezone.utc))
    ]
    out = await svc.showcase()
    assert len(out.scans) == len(out.transcriptions) == len(out.conversations) == 1
    assert out.transcriptions[0].duration_seconds == 123.4
```

(`asyncio_mode = "auto"` — no decorators needed.)

- [ ] **Step 3: Run — expect FAIL** (no `app.services.public_service`).

- [ ] **Step 4: Implement `app/services/public_service.py`**

```python
"""Read-only assembly for the unauthenticated /api/v1/public router.

Rule: a non-public id and a missing id raise the same NotFoundError — the
public surface must not reveal that a private row exists.
"""
from datetime import datetime, timedelta, timezone
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
from app.schemas.transcription import SegmentResponse
from app.services.photogrammetry_service import DOWNLOAD_TTL_SECONDS

SHOWCASE_LIMIT = 20


class PublicService:
    def __init__(self, scans, transcriptions, conversations, storage):
        self._scans = scans
        self._transcriptions = transcriptions
        self._conversations = conversations
        self._storage = storage

    async def showcase(self) -> ShowcaseResponse:
        scans = [self._scan_summary(j) for j in await self._scans.list_public_jobs(SHOWCASE_LIMIT)]
        transcriptions = [
            await self._transcription_summary(j)
            for j in await self._transcriptions.list_public_jobs(SHOWCASE_LIMIT)
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
        summary = await self._transcription_summary(job)
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
        return PublicTranscriptionDetail(**summary.model_dump(), segments=segments)

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

    async def _transcription_summary(self, job) -> PublicTranscriptionSummary:
        duration, count = await self._transcriptions.get_segment_stats(job.id)
        return PublicTranscriptionSummary(
            job_id=job.id,
            created_at=job.created_at,
            duration_seconds=duration,
            segment_count=count or None,
            speaker_count=job.matched_speaker_count,
        )
```

- [ ] **Step 5: Run — expect PASS**, then full `uv run pytest tests/unit -q`.

- [ ] **Step 6: Commit** — `git commit -m "feat(api): PublicService and public repo lookups"`

---

### Task 4: Public router

**Files:**
- Create: `chat-api/app/api/v1/public/__init__.py`, `chat-api/app/api/v1/public/deps.py`, `chat-api/app/api/v1/public/routes.py`
- Modify: `chat-api/app/api/v1/router.py`
- Test: `chat-api/tests/unit/api/test_public.py`

**Interfaces:**
- Consumes: Task 3's `PublicService`; Task 2 schemas.
- Produces: `GET /api/v1/public/showcase`, `GET /api/v1/public/photogrammetry/{job_id}`, `GET /api/v1/public/transcriptions/{job_id}`, `GET /api/v1/public/conversations/{conversation_id}` — no auth of any kind. Provider name `get_public_service` (tests and nothing else override it).

- [ ] **Step 1: Write the failing tests** (note: **no** `get_current_user` override and **no** Authorization header — that is the point):

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.public.deps import get_public_service
from app.core.exceptions import NotFoundError
from app.main import app
from app.schemas.public import PublicScanDetail, ShowcaseResponse


@pytest.fixture
async def client():
    svc = AsyncMock()
    app.dependency_overrides[get_public_service] = lambda: svc
    with patch("app.db.session.init_db", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, svc
    app.dependency_overrides.clear()


async def test_showcase_needs_no_auth(client):
    ac, svc = client
    svc.showcase.return_value = ShowcaseResponse()
    r = await ac.get("/api/v1/public/showcase")
    assert r.status_code == 200
    assert set(r.json()) == {"scans", "transcriptions", "conversations"}


async def test_scan_detail_serves_public_job_without_private_fields(client):
    ac, svc = client
    svc.scan_detail.return_value = PublicScanDetail(
        job_id=uuid4(), name="cat", image_count=22, status="complete",
        preview_url="https://signed", created_at=datetime.now(timezone.utc),
        mesh_url="https://signed",
    )
    r = await ac.get(f"/api/v1/public/photogrammetry/{uuid4()}")
    assert r.status_code == 200
    body = r.json()
    for key in ("user_id", "mesh_s3_key", "input_prefix", "error_message"):
        assert key not in body


async def test_private_and_missing_are_the_same_404(client):
    ac, svc = client
    jid = uuid4()
    svc.scan_detail.side_effect = NotFoundError(f"Job {jid} not found")
    r1 = await ac.get(f"/api/v1/public/photogrammetry/{jid}")
    svc.scan_detail.side_effect = NotFoundError(f"Job {jid} not found")
    r2 = await ac.get(f"/api/v1/public/photogrammetry/{jid}")
    assert r1.status_code == r2.status_code == 404
    assert r1.json() == r2.json()


async def test_transcription_and_conversation_routes_exist(client):
    ac, svc = client
    svc.transcription_detail.side_effect = NotFoundError("Job x not found")
    assert (await ac.get(f"/api/v1/public/transcriptions/{uuid4()}")).status_code == 404
    svc.conversation_detail.side_effect = NotFoundError("Conversation x not found")
    assert (await ac.get(f"/api/v1/public/conversations/{uuid4()}")).status_code == 404
```

- [ ] **Step 2: Run — expect FAIL** (import error).

- [ ] **Step 3: Implement**

`app/api/v1/public/deps.py`:

```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_db
from app.repositories.conversation import ConversationRepository
from app.repositories.photogrammetry import PhotogrammetryRepository
from app.repositories.transcription import TranscriptionRepository
from app.services.audio_storage import AudioStorageService, LocalAudioStorageService
from app.services.public_service import PublicService


def get_public_service(db: AsyncSession = Depends(get_db)) -> PublicService:
    s = get_settings()
    if s.use_mock_photogrammetry or s.use_mock_transcription:
        storage = LocalAudioStorageService(s.mock_upload_base_url, s.local_storage_path)
    else:
        storage = AudioStorageService(s)
    return PublicService(
        PhotogrammetryRepository(db),
        TranscriptionRepository(db),
        ConversationRepository(db),
        storage,
    )
```

`app/api/v1/public/routes.py`:

```python
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
```

`app/api/v1/public/__init__.py`:

```python
from app.api.v1.public.routes import router

__all__ = ["router"]
```

`app/api/v1/router.py` — add the import and, after the `profile` line:

```python
router.include_router(public_router, prefix="/public", tags=["public"])
```

(import as `from app.api.v1.public import router as public_router`).

- [ ] **Step 4: Run — expect PASS**, then full `uv run pytest tests/unit -q` and `uv run ruff check .`.

- [ ] **Step 5: Commit** — `git commit -m "feat(api): unauthenticated /api/v1/public router"`

---

### Task 5: Owner visibility toggles (PATCH)

**Files:**
- Modify: `chat-api/app/api/v1/photogrammetry/jobs.py`, `chat-api/app/api/v1/transcribe/jobs.py`, `chat-api/app/api/v1/endpoints/conversations.py`
- Modify: `chat-api/app/services/photogrammetry_service.py`, `chat-api/app/services/transcription_service.py`, `chat-api/app/services/conversation.py`
- Modify: `chat-api/app/schemas/photogrammetry.py` (`JobStatusResponse`), `chat-api/app/schemas/transcription.py` (`JobStatusResponse`), `chat-api/app/schemas/conversation.py` (`ConversationOut`)
- Test: extend `chat-api/tests/unit/api/test_photogrammetry_jobs.py`, `chat-api/tests/unit/api/test_transcribe_jobs.py`; create `chat-api/tests/unit/api/test_conversations_visibility.py`

**Interfaces:**
- Consumes: `VisibilityRequest` (Task 2), repo `set_is_public` methods (Task 3).
- Produces: `PATCH /api/v1/photogrammetry/jobs/{job_id}`, `PATCH /api/v1/transcribe/jobs/{job_id}`, `PATCH /api/v1/conversations/{conversation_id}` — each takes `{"is_public": bool}`, owner-only, returns the item's usual response schema which now carries `is_public: bool = False`. Service methods: `PhotogrammetryService.set_visibility(user_id, job_id, is_public) -> JobStatusResponse`, `TranscriptionService.set_visibility(user_id, job_id, is_public) -> JobStatusResponse`, `ConversationService.set_visibility(conversation_id, user_sub, is_public) -> ConversationOut`. The SPA (Tasks 7-9) relies on these paths and on `is_public` in the three response schemas.

- [ ] **Step 1: Add `is_public: bool = False`** to `JobStatusResponse` in both schema modules and to `ConversationOut`, and make each populated: photogrammetry's `_to_response` helper and the transcription job-response constructor gain `is_public=job.is_public`; `ConversationOut` uses `from_attributes` so no change beyond the field.

- [ ] **Step 2: Write the failing tests.** Photogrammetry (append to `test_photogrammetry_jobs.py`, using its existing `client` fixture, `H` headers, and mock-service factory — add `set_visibility` to `make_mock_service` returning a `JobStatusResponse` with `is_public=True`):

```python
async def test_patch_visibility(client):
    ac, svc = client
    jid = uuid4()
    r = await ac.patch(f"/api/v1/photogrammetry/jobs/{jid}", json={"is_public": True}, headers=H)
    assert r.status_code == 200 and r.json()["is_public"] is True
    svc.set_visibility.assert_awaited_once_with("user1", jid, True)


async def test_patch_visibility_not_owner_is_404(client):
    ac, svc = client
    svc.set_visibility.side_effect = NotFoundError("Job x not found")
    r = await ac.patch(f"/api/v1/photogrammetry/jobs/{uuid4()}", json={"is_public": True}, headers=H)
    assert r.status_code == 404
```

Mirror the same two tests in `test_transcribe_jobs.py` with its fixture. Conversations (new file; the router builds `ConversationService(db)` inline, so patch the class):

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import ForbiddenError
from app.dependencies import get_current_user, get_db
from app.main import app
from app.schemas.conversation import ConversationOut


@pytest.fixture
async def client():
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user1"}
    app.dependency_overrides[get_db] = lambda: None
    with patch("app.db.session.init_db", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


async def test_patch_conversation_visibility(client):
    cid = uuid4()
    out = ConversationOut(
        id=cid, title="t", model_id="m", is_public=True,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    with patch("app.api.v1.endpoints.conversations.ConversationService") as cls:
        cls.return_value.set_visibility = AsyncMock(return_value=out)
        r = await client.patch(f"/api/v1/conversations/{cid}", json={"is_public": True})
    assert r.status_code == 200 and r.json()["is_public"] is True
    cls.return_value.set_visibility.assert_awaited_once_with(cid, user_sub="user1", is_public=True)


async def test_patch_conversation_not_owner_is_403(client):
    with patch("app.api.v1.endpoints.conversations.ConversationService") as cls:
        cls.return_value.set_visibility = AsyncMock(side_effect=ForbiddenError("Access denied"))
        r = await client.patch(f"/api/v1/conversations/{uuid4()}", json={"is_public": True})
    assert r.status_code == 403
```

(`ConversationOut`'s exact required fields: match its definition in `app/schemas/conversation.py:7-16` when constructing.)

- [ ] **Step 3: Run — expect FAIL** (405s / missing service methods).

- [ ] **Step 4: Implement.** Endpoints (photogrammetry shown; transcribe is identical against its own service; both import `VisibilityRequest` from `app.schemas.public`):

```python
@router.patch("/jobs/{job_id}", response_model=JobStatusResponse)
async def set_job_visibility(
    job_id: UUID,
    body: VisibilityRequest,
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> JobStatusResponse:
    return await service.set_visibility(current_user["sub"], job_id, body.is_public)
```

Conversations endpoint:

```python
@router.patch("/{conversation_id}", response_model=ConversationOut)
async def set_conversation_visibility(
    conversation_id: UUID,
    body: VisibilityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    service = ConversationService(db)
    return await service.set_visibility(
        conversation_id, user_sub=current_user["sub"], is_public=body.is_public
    )
```

Service methods — photogrammetry/transcription toggle then return the same response the GET handler serves (photogrammetry: `get_job_status`; transcription: whatever `GET /transcribe/jobs/{job_id}` at `app/api/v1/transcribe/jobs.py:56` calls — reuse that method by name):

```python
    async def set_visibility(self, user_id: str, job_id: UUID, is_public: bool) -> JobStatusResponse:
        job = await self._repo.set_is_public(job_id, user_id, is_public)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        return await self.get_job_status(user_id, job_id)
```

(Match each service's actual repo attribute name — `self._repo` vs `self.repo` — and its status-response method name.) Conversation service:

```python
    async def set_visibility(self, conversation_id: UUID, *, user_sub: str, is_public: bool) -> ConversationOut:
        conversation = await self._repo.set_is_public(conversation_id, user_sub, is_public)
        return ConversationOut.model_validate(conversation)
```

- [ ] **Step 5: Run — expect PASS**, then full `uv run pytest tests/unit -q` and `uv run ruff check .`.

- [ ] **Step 6: Commit** — `git commit -m "feat(api): owner PATCH toggles for public visibility"`

---

### Task 6: SPA — public types + API client

**Files:**
- Modify: `chat-vue/src/types/index.ts` (append public types; add `is_public?: boolean` to `Conversation` (line 11), `TranscriptionJob` (line 82), `PhotogrammetryJob` (line 253))
- Create: `chat-vue/src/lib/publicApi.ts`
- Modify: `chat-vue/src/lib/photogrammetryApi.ts`, `chat-vue/src/lib/transcribeApi.ts` (add `setJobVisibility`)
- Test: `chat-vue/src/lib/__tests__/publicApi.spec.ts`

**Interfaces:**
- Consumes: backend routes from Tasks 4-5; `apiClient` from `@/lib/axios` (sends no Authorization header when logged out — already conditional).
- Produces: `getShowcase(): Promise<ShowcaseResponse>`, `getPublicScan(jobId)`, `getPublicTranscription(jobId)`, `getPublicConversation(id)`; `photogrammetryApi.setJobVisibility(jobId, isPublic)`, `transcribeApi.setJobVisibility(jobId, isPublic)`. TS interfaces mirroring Task 2's schemas exactly (snake_case fields, ISO strings for datetimes).

- [ ] **Step 1: Append to `src/types/index.ts`:**

```ts
// ── Public demo (mirrors chat-api app/schemas/public.py) ─────────────────────
export interface PublicScanSummary {
  job_id: string
  name: string
  image_count: number
  status: string
  preview_url: string | null
  created_at: string
}

export interface PublicScanDetail extends PublicScanSummary {
  warnings: string[]
  matched: number | null
  total: number | null
  mesh_url: string | null
  expires_at: string | null
  completed_at: string | null
}

export interface PublicTranscriptionSummary {
  job_id: string
  created_at: string
  duration_seconds: number | null
  segment_count: number | null
  speaker_count: number | null
}

export interface PublicTranscriptionDetail extends PublicTranscriptionSummary {
  segments: TranscriptSegment[]
}

export interface PublicMessage {
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface PublicConversationSummary {
  conversation_id: string
  title: string | null
  model_id: string | null
  created_at: string
}

export interface PublicConversationDetail extends PublicConversationSummary {
  messages: PublicMessage[]
}

export interface ShowcaseResponse {
  scans: PublicScanSummary[]
  transcriptions: PublicTranscriptionSummary[]
  conversations: PublicConversationSummary[]
}
```

And add `is_public?: boolean` to the three existing interfaces named above.

- [ ] **Step 2: Write the failing spec** (same pattern as `src/lib/__tests__/photogrammetryApi.spec.ts` — mock `@/lib/axios`):

```ts
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/axios", () => ({
  apiClient: { get: vi.fn(), patch: vi.fn() },
}))

import { apiClient } from "@/lib/axios"
import { getPublicScan, getShowcase } from "../publicApi"

const get = apiClient.get as ReturnType<typeof vi.fn>

describe("publicApi", () => {
  beforeEach(() => vi.clearAllMocks())

  it("fetches the showcase", async () => {
    get.mockResolvedValue({ data: { scans: [], transcriptions: [], conversations: [] } })
    const out = await getShowcase()
    expect(get).toHaveBeenCalledWith("/api/v1/public/showcase")
    expect(out.scans).toEqual([])
  })

  it("fetches a public scan", async () => {
    get.mockResolvedValue({ data: { job_id: "j1" } })
    await getPublicScan("j1")
    expect(get).toHaveBeenCalledWith("/api/v1/public/photogrammetry/j1")
  })
})
```

- [ ] **Step 3: Run — expect FAIL**: `cd chat-vue && npx vitest run src/lib/__tests__/publicApi.spec.ts`

- [ ] **Step 4: Implement `src/lib/publicApi.ts`:**

```ts
import { apiClient } from "@/lib/axios"
import type {
  PublicConversationDetail,
  PublicScanDetail,
  PublicTranscriptionDetail,
  ShowcaseResponse,
} from "@/types"

const BASE = "/api/v1/public"

export async function getShowcase(): Promise<ShowcaseResponse> {
  return (await apiClient.get(`${BASE}/showcase`)).data
}

export async function getPublicScan(jobId: string): Promise<PublicScanDetail> {
  return (await apiClient.get(`${BASE}/photogrammetry/${jobId}`)).data
}

export async function getPublicTranscription(jobId: string): Promise<PublicTranscriptionDetail> {
  return (await apiClient.get(`${BASE}/transcriptions/${jobId}`)).data
}

export async function getPublicConversation(id: string): Promise<PublicConversationDetail> {
  return (await apiClient.get(`${BASE}/conversations/${id}`)).data
}
```

Add to `src/lib/photogrammetryApi.ts` (and the equivalent, with its literal `/api/v1/transcribe` path style, to `transcribeApi.ts`):

```ts
export async function setJobVisibility(jobId: string, isPublic: boolean): Promise<JobStatusResponse> {
  return (await apiClient.patch(`${BASE}/jobs/${jobId}`, { is_public: isPublic })).data
}
```

(Use each file's existing response-type import for the job status shape — `PhotogrammetryJob` / `TranscriptionJob` from `@/types` if that's what its `getJob`/`getJobStatus` return.)

- [ ] **Step 5: Run — expect PASS**, then `npm run test`.

- [ ] **Step 6: Commit** — `git commit -m "feat(vue): public API client and types"`

---

### Task 7: SPA — /demo route, guard redirect, DemoView

**Files:**
- Modify: `chat-vue/src/router/index.ts`
- Create: `chat-vue/src/views/DemoView.vue`
- Test: `chat-vue/src/router/__tests__/guard.spec.ts`, `chat-vue/src/views/__tests__/DemoView.spec.ts`

**Interfaces:**
- Consumes: `publicApi` (Task 6); `MeshViewer` (props `src/poster/mock/pending`), `TranscriptDisplay` (prop `transcript: { segments }`), `MessageList` (props `messages: Message[]`, `isSending`), `useAuthStore` (`isAuthenticated`, `login()`).
- Produces: route `{ path: '/demo', name: 'demo' }` with **no** `requiresAuth`; exported `authGuard` function; logged-out visits to any guarded route land on `/demo`.

- [ ] **Step 1: Write the failing guard test** (`src/router/__tests__/guard.spec.ts` — first router test in the repo; the auth store reads `localStorage`, so clear it):

```ts
import { beforeEach, describe, expect, it } from "vitest"
import { createPinia, setActivePinia } from "pinia"

import { authGuard } from "../index"
import { useAuthStore } from "@/stores/auth"

function to(meta: Record<string, unknown>) {
  return { meta } as never
}

// isAdmin decodes the JWT payload (stores/auth.ts:18-28), so the token must be well-formed
function makeToken(groups: string[] = []): string {
  return `h.${btoa(JSON.stringify({ "cognito:groups": groups }))}.s`
}

describe("authGuard", () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it("sends logged-out visitors to the demo instead of Cognito", () => {
    expect(authGuard(to({ requiresAuth: true }))).toEqual({ name: "demo" })
  })

  it("lets logged-out visitors reach unguarded routes", () => {
    expect(authGuard(to({}))).toBeUndefined()
  })

  it("passes authenticated users through", () => {
    const auth = useAuthStore()
    auth.token = makeToken()
    expect(authGuard(to({ requiresAuth: true }))).toBeUndefined()
  })

  it("bounces non-admins off admin routes", () => {
    const auth = useAuthStore()
    auth.token = makeToken()
    expect(authGuard(to({ requiresAuth: true, requiresAdmin: true }))).toEqual({ name: "chat" })
  })
})
```

- [ ] **Step 2: Run — expect FAIL** (`authGuard` not exported).

- [ ] **Step 3: Modify `src/router/index.ts`** — add the route (with the other lazy routes; no `meta`):

```ts
  {
    path: '/demo',
    name: 'demo',
    component: () => import('@/views/DemoView.vue'),
  },
```

Replace the `router.beforeEach((to) => { … })` closure (lines 62-71) with an exported function registered once:

```ts
export function authGuard(to: RouteLocationNormalized) {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { name: 'demo' }
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return { name: 'chat' }
  }
}

router.beforeEach(authGuard)
```

(`import type { RouteLocationNormalized } from 'vue-router'`. `auth.login()` is no longer called by the guard — the demo page's Sign in button owns that.)

- [ ] **Step 4: Create `src/views/DemoView.vue`** — public landing: hero ("aiTools — chat · transcribe · photogrammetry", "Sign in" / "Open the app"), then one section per feature from the showcase payload; a scan card click loads the mesh into `MeshViewer`, a transcript loads into `TranscriptDisplay`, a conversation into `MessageList`:

```vue
<script setup lang="ts">
import { onMounted, ref } from "vue"

import MeshViewer from "@/components/photogrammetry/MeshViewer.vue"
import MessageList from "@/components/MessageList.vue"
import TranscriptDisplay from "@/components/transcribe/TranscriptDisplay.vue"
import {
  getPublicConversation,
  getPublicScan,
  getPublicTranscription,
  getShowcase,
} from "@/lib/publicApi"
import { useAuthStore } from "@/stores/auth"
import type {
  Message,
  PublicScanDetail,
  PublicTranscriptionDetail,
  ShowcaseResponse,
} from "@/types"

const auth = useAuthStore()
const showcase = ref<ShowcaseResponse | null>(null)
const loadError = ref(false)
const scan = ref<PublicScanDetail | null>(null)
const scanPending = ref(false)
const transcript = ref<PublicTranscriptionDetail | null>(null)
const messages = ref<Message[] | null>(null)
const activeConversationId = ref<string | null>(null)

onMounted(async () => {
  try {
    showcase.value = await getShowcase()
    const first = showcase.value.scans.find((s) => s.status === "complete")
    if (first) await openScan(first.job_id)
  } catch {
    loadError.value = true
  }
})

async function openScan(jobId: string) {
  scanPending.value = true
  try {
    scan.value = await getPublicScan(jobId)
  } finally {
    scanPending.value = false
  }
}

async function openTranscription(jobId: string) {
  transcript.value = await getPublicTranscription(jobId)
}

async function openConversation(id: string) {
  activeConversationId.value = id
  const detail = await getPublicConversation(id)
  messages.value = detail.messages.map((m, i) => ({
    id: `${id}-${i}`,
    role: m.role,
    content: m.content,
    timestamp: new Date(m.created_at),
  }))
}

function durationLabel(seconds: number | null): string {
  if (!seconds) return ""
  const m = Math.floor(seconds / 60)
  return `${m}m${Math.round(seconds % 60)}s`
}
</script>

<template>
  <div class="min-h-screen overflow-y-auto bg-gray-50 text-gray-900">
    <header class="border-b border-gray-200 bg-white px-6 py-4">
      <div class="mx-auto flex max-w-5xl items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold">aiTools</h1>
          <p class="text-sm text-gray-500">chat · transcribe · photogrammetry — a live demo of real results</p>
        </div>
        <RouterLink
          v-if="auth.isAuthenticated"
          to="/"
          class="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
        >Open the app</RouterLink>
        <button
          v-else
          type="button"
          class="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
          data-testid="sign-in"
          @click="auth.login()"
        >Sign in</button>
      </div>
    </header>

    <main class="mx-auto max-w-5xl space-y-10 px-6 py-8">
      <p v-if="loadError" class="text-sm text-red-600" data-testid="demo-error">
        The demo backend is unreachable right now.
      </p>

      <section v-if="showcase?.scans.length" data-testid="section-scans">
        <h2 class="mb-1 text-lg font-semibold">Photogrammetry</h2>
        <p class="mb-3 text-sm text-gray-500">
          Photos in, textured 3D mesh out — COLMAP + OpenMVS on a spot GPU. Drag to orbit.
        </p>
        <div class="mb-3 flex flex-wrap gap-2">
          <button
            v-for="s in showcase.scans"
            :key="s.job_id"
            type="button"
            class="rounded border px-2.5 py-1 text-xs font-medium"
            :class="scan?.job_id === s.job_id ? 'border-indigo-400 bg-indigo-50 text-indigo-700' : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-100'"
            data-testid="scan-chip"
            @click="openScan(s.job_id)"
          >{{ s.name }} · {{ s.image_count }} photos</button>
        </div>
        <div class="h-96 overflow-hidden rounded border border-gray-200 bg-white">
          <MeshViewer
            :src="scan?.mesh_url ?? null"
            :poster="scan?.preview_url ?? null"
            :mock="false"
            :pending="scanPending"
          />
        </div>
        <p v-if="scan?.matched != null" class="mt-2 text-xs text-gray-500">
          {{ scan.matched }} of {{ scan.total }} photos matched by structure-from-motion
        </p>
      </section>

      <section v-if="showcase?.transcriptions.length" data-testid="section-transcriptions">
        <h2 class="mb-1 text-lg font-semibold">Transcription</h2>
        <p class="mb-3 text-sm text-gray-500">
          Speaker diarization (pyannote) + voice matching against enrolled speaker profiles.
        </p>
        <div class="mb-3 flex flex-wrap gap-2">
          <button
            v-for="t in showcase.transcriptions"
            :key="t.job_id"
            type="button"
            class="rounded border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100"
            data-testid="transcription-chip"
            @click="openTranscription(t.job_id)"
          >{{ new Date(t.created_at).toLocaleDateString() }} · {{ durationLabel(t.duration_seconds) }}</button>
        </div>
        <div v-if="transcript" class="rounded border border-gray-200 bg-white p-4">
          <TranscriptDisplay :transcript="{ segments: transcript.segments }" />
        </div>
      </section>

      <section v-if="showcase?.conversations.length" data-testid="section-conversations">
        <h2 class="mb-1 text-lg font-semibold">Chat</h2>
        <p class="mb-3 text-sm text-gray-500">Claude via AWS Bedrock, per-conversation model choice.</p>
        <div class="mb-3 flex flex-wrap gap-2">
          <button
            v-for="c in showcase.conversations"
            :key="c.conversation_id"
            type="button"
            class="rounded border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100"
            data-testid="conversation-chip"
            @click="openConversation(c.conversation_id)"
          >{{ c.title ?? "Untitled" }}</button>
        </div>
        <div v-if="messages" class="rounded border border-gray-200 bg-white">
          <MessageList :messages="messages" :is-sending="false" />
        </div>
      </section>
    </main>
  </div>
</template>
```

- [ ] **Step 5: Write the DemoView spec** (`src/views/__tests__/DemoView.spec.ts` — mock model-viewer and the public API):

```ts
import { describe, expect, it, vi } from "vitest"
import { flushPromises, mount, RouterLinkStub } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@google/model-viewer", () => ({ ModelViewerElement: class {} }))
vi.mock("@/lib/publicApi", () => ({
  getShowcase: vi.fn(),
  getPublicScan: vi.fn(),
  getPublicTranscription: vi.fn(),
  getPublicConversation: vi.fn(),
}))

import { getPublicScan, getShowcase } from "@/lib/publicApi"
import DemoView from "../DemoView.vue"

const showcase = {
  scans: [{ job_id: "j1", name: "cat", image_count: 22, status: "complete", preview_url: null, created_at: "2026-09-01T00:00:00Z" }],
  transcriptions: [],
  conversations: [],
}

function mountDemo() {
  localStorage.clear()
  setActivePinia(createPinia())
  return mount(DemoView, { global: { stubs: { RouterLink: RouterLinkStub } } })
}

describe("DemoView", () => {
  it("renders the showcase and auto-opens the first complete scan", async () => {
    vi.mocked(getShowcase).mockResolvedValue(showcase as never)
    vi.mocked(getPublicScan).mockResolvedValue({ ...showcase.scans[0], warnings: [], matched: 20, total: 22, mesh_url: "https://signed", expires_at: null, completed_at: null } as never)
    const w = mountDemo()
    await flushPromises()
    expect(w.find('[data-testid="section-scans"]').exists()).toBe(true)
    expect(getPublicScan).toHaveBeenCalledWith("j1")
    expect(w.find('[data-testid="sign-in"]').exists()).toBe(true)
  })

  it("shows the error note when the API is unreachable", async () => {
    vi.mocked(getShowcase).mockRejectedValue(new Error("down"))
    const w = mountDemo()
    await flushPromises()
    expect(w.find('[data-testid="demo-error"]').exists()).toBe(true)
  })
})
```

- [ ] **Step 6: Run — expect PASS**: `npm run test`. Also run `npx vue-tsc -p tsconfig.app.json --noEmit` — only the four pre-existing `components/transcribe/*.vue` errors may appear.

- [ ] **Step 7: Commit** — `git commit -m "feat(vue): /demo public showcase; guard sends visitors there"`

---

### Task 8: SPA — Public toggles on owned items

**Files:**
- Create: `chat-vue/src/components/PublicToggle.vue`
- Modify: `chat-vue/src/components/photogrammetry/ScanDetailView.vue` (header, lines 170-218), `chat-vue/src/components/transcribe/RunDetailView.vue` (job-header block, lines 103-110), `chat-vue/src/components/ConversationSidebar.vue` (conversation rows, lines 39-56)
- Modify: `chat-vue/src/stores/photogrammetry.ts`, `chat-vue/src/stores/transcribe.ts`, `chat-vue/src/stores/chat.ts`
- Test: `chat-vue/src/components/__tests__/PublicToggle.spec.ts`; extend `chat-vue/src/components/photogrammetry/__tests__/ScanDetailView.spec.ts`

**Interfaces:**
- Consumes: `setJobVisibility` from both API modules (Task 6); `PATCH /api/v1/conversations/{id}` (Task 5); `is_public` on the three types.
- Produces: `PublicToggle` props `{ isPublic: boolean; busy?: boolean }`, emit `toggle(next: boolean)`; store actions `setVisibility(jobId: string, isPublic: boolean)` on the photogrammetry and transcribe stores, `setConversationVisibility(id: string, isPublic: boolean)` on the chat store.

- [ ] **Step 1: Write the failing component spec:**

```ts
import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"

import PublicToggle from "../PublicToggle.vue"

describe("PublicToggle", () => {
  it("shows state and emits the flipped value", async () => {
    const w = mount(PublicToggle, { props: { isPublic: false } })
    expect(w.text()).toContain("Make public")
    await w.find('[data-testid="public-toggle"]').trigger("click")
    expect(w.emitted("toggle")![0]).toEqual([true])
  })

  it("reads Public when on and disables while busy", () => {
    const w = mount(PublicToggle, { props: { isPublic: true, busy: true } })
    expect(w.text()).toContain("Public")
    expect(w.find("button").attributes("disabled")).toBeDefined()
  })
})
```

- [ ] **Step 2: Run — expect FAIL.** Implement `src/components/PublicToggle.vue`:

```vue
<script setup lang="ts">
defineProps<{ isPublic: boolean; busy?: boolean }>()
const emit = defineEmits<{ toggle: [next: boolean] }>()
</script>

<template>
  <button
    type="button"
    class="rounded border px-2.5 py-1 text-xs font-medium disabled:opacity-50"
    :class="isPublic ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-100'"
    :disabled="busy"
    :title="isPublic ? 'Shown on the public demo page — click to make private' : 'Private — click to show on the public demo page'"
    data-testid="public-toggle"
    @click="emit('toggle', !isPublic)"
  >{{ isPublic ? 'Public' : 'Make public' }}</button>
</template>
```

- [ ] **Step 3: Store actions.** Photogrammetry store (exports list at the bottom of the file — add `setVisibility`):

```ts
  async function setVisibility(jobId: string, isPublic: boolean) {
    const updated = await api.setJobVisibility(jobId, isPublic)
    const idx = jobs.value.findIndex((j) => j.job_id === updated.job_id)
    if (idx >= 0) jobs.value[idx] = { ...jobs.value[idx], ...updated }
  }
```

Transcribe store: same shape against its `setJobVisibility` and its jobs array (match the store's job id field name — the transcribe job objects use `job_id`). Chat store (inline axios, like its other calls):

```ts
  async function setConversationVisibility(id: string, isPublic: boolean) {
    const { data } = await apiClient.patch(`/api/v1/conversations/${id}`, { is_public: isPublic })
    const conv = conversations.value.find((c) => c.id === id)
    if (conv) conv.is_public = data.is_public
  }
```

Export each new action from its store's return block.

- [ ] **Step 4: Wire the toggle into the three surfaces.**

`ScanDetailView.vue` — in the header's `div.ml-auto` (line 176), before the tablist:

```vue
          <PublicToggle
            :is-public="job.is_public ?? false"
            :busy="visibilityBusy"
            @toggle="(next) => setVisibility(next)"
          />
```

with, in its script block:

```ts
const visibilityBusy = ref(false)
async function setVisibility(next: boolean) {
  if (!job.value) return
  visibilityBusy.value = true
  try {
    await store.setVisibility(job.value.job_id, next)
  } finally {
    visibilityBusy.value = false
  }
}
```

`RunDetailView.vue` — inside the job-header block (line 104-110), above `TranscribeJobCard`:

```vue
        <div class="mb-2 flex justify-end">
          <PublicToggle
            v-if="activeJob"
            :is-public="activeJob.is_public ?? false"
            :busy="visibilityBusy"
            @toggle="(next) => setVisibility(next)"
          />
        </div>
```

(same script pattern against `store.setVisibility(activeJob.job_id, next)`).

`ConversationSidebar.vue` — in the conversation row (lines 39-56), rendered only for the active conversation, next to the existing delete affordance:

```vue
            <PublicToggle
              v-if="conversation.id === store.activeConversationId"
              :is-public="conversation.is_public ?? false"
              @toggle="(next) => store.setConversationVisibility(conversation.id, next)"
            />
```

(adjust the local names to the file's actual `v-for` variable and store binding; use `@click.stop` on the toggle's wrapper if the row itself is a button).

- [ ] **Step 5: Extend `ScanDetailView.spec.ts`** — add `setJobVisibility: vi.fn()` to its `vi.mock("@/lib/photogrammetryApi", …)` factory, then:

```ts
  it("toggles visibility through the store", async () => {
    const { wrapper, store } = await mountWithJob()  // use the file's existing setup helper/pattern
    ;(api.setJobVisibility as Mock).mockResolvedValue({ ...store.jobs[0], is_public: true })
    await wrapper.find('[data-testid="public-toggle"]').trigger("click")
    await flushPromises()
    expect(api.setJobVisibility).toHaveBeenCalledWith("j1", true)
  })
```

(Adapt the mount call to the spec file's existing helpers — it already mounts with a seeded store and `selectJob("j1")`.)

- [ ] **Step 6: Run — expect PASS**: `npm run test`, and `npx vue-tsc -p tsconfig.app.json --noEmit` (only the four known pre-existing errors).

- [ ] **Step 7: Commit** — `git commit -m "feat(vue): Public toggles on scans, runs, conversations"`

---

### Task 9: Docs

**Files:**
- Modify: `chat-api/CLAUDE.md` (endpoints table: add the `public` router row and the three PATCH routes; migrations note "latest:" → `u1v2w3x4y5z6`)
- Modify: `chat-vue/CLAUDE.md` (router list + views: add `/demo` → DemoView, `lib/publicApi.ts`, `PublicToggle.vue`; Auth Flow: guard now redirects to `/demo` instead of calling `login()`)
- Modify: `docs/user-guide.md` (short "Demo" section: the demo page, what Public toggles do, that public items are visible to anyone)

**Interfaces:** none.

- [ ] **Step 1:** Make the three edits, each a sentence or table row in the file's existing voice — no new sections beyond the user-guide's "Demo" heading.

- [ ] **Step 2:** Run: `cd chat-api && uv run pytest tests/unit -q && cd ../chat-vue && npm run test`
Expected: both suites green (docs changes can't break them — this is the plan's final full-suite gate).

- [ ] **Step 3: Commit** — `git commit -m "docs: public demo endpoints, /demo route, user guide"`
