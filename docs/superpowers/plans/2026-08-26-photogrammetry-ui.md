# Photogrammetry UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/photogrammetry` page on chat.peaslee.org where a user drops 5–150 photos, a job walks `pending → queued → processing(sfm→dense→mesh→texture) → complete`, and the resulting GLB renders in-browser — backed for now by an in-process API mock and a committed sample photo set, with the real worker's contract fixed.

**Architecture:** A new vertical mirroring the transcribe feature: `photogrammetry_jobs` table + `PhotogrammetryRepository` + `PhotogrammetryService`/`LocalPhotogrammetryService` + `/api/v1/photogrammetry` router in `chat-api`; a `photogrammetry` Pinia store, `PhotogrammetryView` and `components/photogrammetry/*` in `chat-vue`. Uploads go browser → presigned PUT (S3 in prod, the existing `dev-upload` sink in mock mode). The mock walks the state machine on `asyncio` timers and serves a committed placeholder GLB through the sink.

**Tech Stack:** FastAPI + SQLAlchemy 2 async + Alembic + pytest-asyncio (chat-api); Vue 3 + TypeScript + Pinia + Tailwind + Vite, `@google/model-viewer` (chat-vue); Pillow + trimesh for the one-off sample-asset script.

**Spec:** `docs/design/photogrammetry-ui-spec.md`

## Global Constraints

- Repo is **public**. No account IDs, ARNs, bucket names, hostnames or cost figures in code, docs, tests or commit messages. Sample photos must have **all EXIF stripped**.
- Nothing in `transcribe/` is refactored. The only transcribe file touched is `app/api/v1/transcribe/__init__.py` (sink registration condition) and `dev.py` (sink GET serves files), plus the nav tab in `RunSidebar.vue`.
- API field names follow the codebase convention: `job_id` (not `id`), cursor pagination `{items, next_cursor}`.
- Image count bounds: `MIN_IMAGES = 5` (constant), `PHOTOGRAMMETRY_MAX_IMAGES = 150` (setting). Allowed extensions `jpg jpeg png`.
- Input keys: `photogrammetry/<user_id>/<job_id>/input/0001.<ext>` (4-digit, 1-based, extension lower-cased). Output keys `…/output/mesh.glb`, `…/output/preview.png`.
- State machine: `pending | queued | processing | complete | failed`; `stage ∈ sfm | dense | mesh | texture`, set only while `processing`.
- Every status response carries `mock: bool`; the UI shows a placeholder notice when true.
- Python: `ruff` line length 100; tests under `chat-api/tests/unit/…` with `asyncio_mode = auto`. Run tests with `cd chat-api && uv run pytest tests/unit -q`.
- Vue: no test runner — `npm run type-check` and `npm run build` are the gates.
- Commit after every task; messages in the repo's `type(scope): summary` style.

## File map

**chat-api (create)**
- `app/models/photogrammetry.py` — `PhotogrammetryJob` ORM model
- `app/db/migrations/versions/l2m3n4o5p6q7_add_photogrammetry_jobs.py` — table + enum
- `app/schemas/photogrammetry.py` — request/response models, `MIN_IMAGES`, `ALLOWED_EXTENSIONS`
- `app/repositories/photogrammetry.py` — `PhotogrammetryRepository`
- `app/services/photogrammetry_service.py` — `PhotogrammetryService`, `LocalPhotogrammetryService`
- `app/api/v1/photogrammetry/{__init__,deps,jobs}.py` — router
- `app/assets/photogrammetry/{images/*.jpg, mesh.glb, preview.png}` — sample assets
- `tests/unit/repositories/test_photogrammetry_repository.py`
- `tests/unit/services/test_photogrammetry_service.py`
- `tests/unit/api/test_photogrammetry_jobs.py`, `tests/unit/api/test_photogrammetry_deps.py`

**chat-api (modify)**
- `app/config.py`, `.env.example` — new settings
- `app/models/__init__.py`, `app/db/migrations/env.py` — import the model
- `app/core/exceptions.py` — `UploadIncomplete`, `WorkerNotDeployed`, `ImageCountOutOfRange`
- `app/services/audio_storage.py` — `generate_presigned_download_url` on all three classes; `write_object` on Local/Mock
- `app/api/v1/transcribe/dev.py` — GET sink serves the file when it exists
- `app/api/v1/transcribe/__init__.py` — sink registered when either mock flag is set
- `app/api/v1/router.py` — mount `/photogrammetry`
- `CLAUDE.md` — layout, env table, mock notes

**repo root**
- `scripts/dev/make-photogrammetry-sample.py` — sample asset generator
- `docs/mock-api.md`, `CLAUDE.md` — docs

**chat-vue (create)**
- `src/lib/photogrammetryApi.ts`, `src/stores/photogrammetry.ts`
- `src/views/PhotogrammetryView.vue`
- `src/components/photogrammetry/{ScanSidebar,ScanJobCard,ScanStatusBadge,StageStrip,ImageDropzone,NewScanForm,ScanDetailView,MeshViewer}.vue`

**chat-vue (modify)**
- `src/types/index.ts`, `src/router/index.ts`, `vite.config.ts`, `package.json`
- `src/components/ConversationSidebar.vue`, `src/components/transcribe/RunSidebar.vue` — third nav tab
- `CLAUDE.md`

---

### Task 1: Model, migration, settings

**Files:**
- Create: `chat-api/app/models/photogrammetry.py`
- Create: `chat-api/app/db/migrations/versions/l2m3n4o5p6q7_add_photogrammetry_jobs.py`
- Modify: `chat-api/app/models/__init__.py`, `chat-api/app/db/migrations/env.py:10-12`
- Modify: `chat-api/app/config.py` (after the `# Sample audio` block), `chat-api/.env.example` (after the `# Audio Transcription` block)
- Test: `chat-api/tests/unit/test_photogrammetry_model.py`

**Interfaces:**
- Produces: `app.models.photogrammetry.PhotogrammetryJob` with columns `id, user_id, name, status, stage, image_count, input_prefix, mesh_s3_key, preview_s3_key, error_message, created_at, updated_at, completed_at`; `Settings.use_mock_photogrammetry: bool`, `mock_photogrammetry_stage_delay_seconds: float`, `photogrammetry_max_images: int`, `photogrammetry_sample_prefix: str`, `gpu_photogrammetry_task_family: str`.

- [ ] **Step 1: Write the failing test**

`chat-api/tests/unit/test_photogrammetry_model.py`:
```python
"""PhotogrammetryJob model shape and default settings."""
from sqlalchemy import Enum as SAEnum

from app.config import Settings
from app.models.base import Base


def test_photogrammetry_jobs_table_is_registered():
    import app.models  # noqa: F401  (imports every model module)
    table = Base.metadata.tables["photogrammetry_jobs"]
    cols = set(table.columns.keys())
    assert {
        "id", "user_id", "name", "status", "stage", "image_count", "input_prefix",
        "mesh_s3_key", "preview_s3_key", "error_message",
        "created_at", "updated_at", "completed_at",
    } <= cols
    status = table.columns["status"].type
    assert isinstance(status, SAEnum)
    assert set(status.enums) == {"pending", "queued", "processing", "complete", "failed"}
    assert status.name == "photogrammetry_job_status"


def test_photogrammetry_settings_defaults():
    s = Settings(_env_file=None)
    assert s.use_mock_photogrammetry is False
    assert s.mock_photogrammetry_stage_delay_seconds == 2.0
    assert s.photogrammetry_max_images == 150
    assert s.photogrammetry_sample_prefix == "samples/photogrammetry/"
    assert s.gpu_photogrammetry_task_family == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd chat-api && uv run pytest tests/unit/test_photogrammetry_model.py -q`
Expected: FAIL — `KeyError: 'photogrammetry_jobs'` and `AttributeError` on the settings.

- [ ] **Step 3: Create the model**

`chat-api/app/models/photogrammetry.py`:
```python
"""Photogrammetry jobs: one row per photo set submitted for reconstruction.

Input images are not rows — `input_prefix` + `image_count` describe them; keys are
`<input_prefix>0001.<ext>` … . Outputs are written by the worker under `…/output/`.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum as SAEnum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin

JOB_STATUSES = ("pending", "queued", "processing", "complete", "failed")
STAGES = ("sfm", "dense", "mesh", "texture")


class PhotogrammetryJob(UUIDMixin, Base):
    __tablename__ = "photogrammetry_jobs"

    user_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(*JOB_STATUSES, name="photogrammetry_job_status"),
        nullable=False,
        default="pending",
    )
    stage: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    input_prefix: Mapped[str] = mapped_column(String(1024), nullable=False)
    mesh_s3_key: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    preview_s3_key: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

`chat-api/app/models/__init__.py` — append:
```python
import app.models.photogrammetry  # noqa: F401
```

`chat-api/app/db/migrations/env.py` — after `import app.models.gpu  # noqa: F401` add:
```python
import app.models.photogrammetry  # noqa: F401
```

- [ ] **Step 4: Create the migration**

`chat-api/app/db/migrations/versions/l2m3n4o5p6q7_add_photogrammetry_jobs.py`:
```python
"""add photogrammetry_jobs

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, None] = "k1l2m3n4o5p6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUS_ENUM = postgresql.ENUM(
    "pending", "queued", "processing", "complete", "failed",
    name="photogrammetry_job_status",
    create_type=False,
)


def upgrade() -> None:
    STATUS_ENUM.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "photogrammetry_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(256), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", STATUS_ENUM, nullable=False, server_default="pending"),
        sa.Column("stage", sa.String(20), nullable=True),
        sa.Column("image_count", sa.Integer(), nullable=False),
        sa.Column("input_prefix", sa.String(1024), nullable=False),
        sa.Column("mesh_s3_key", sa.String(1024), nullable=True),
        sa.Column("preview_s3_key", sa.String(1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_photogrammetry_jobs_user_id", "photogrammetry_jobs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_photogrammetry_jobs_user_id", table_name="photogrammetry_jobs")
    op.drop_table("photogrammetry_jobs")
    STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 5: Add settings**

`chat-api/app/config.py` — insert after the `sample_jane_s3_key` line:
```python
    # Photogrammetry (spec: docs/design/photogrammetry-ui-spec.md)
    use_mock_photogrammetry: bool = False
    # Seconds spent in each mock stage: queued → sfm → dense → mesh → texture → complete
    mock_photogrammetry_stage_delay_seconds: float = 2.0
    photogrammetry_max_images: int = 150
    # Shared sample photo set in the audio bucket, uploaded once by hand (images/0001.jpg …)
    photogrammetry_sample_prefix: str = "samples/photogrammetry/"
    # ECS task family of the photogrammetry worker; empty = not deployed (confirm returns 503)
    gpu_photogrammetry_task_family: str = ""
```

`chat-api/.env.example` — insert after the `#MOCK_JOB_MATCHING_DELAY_SECONDS=3.0` line:
```
# Photogrammetry
# Skip S3/ECS; jobs walk queued → sfm → dense → mesh → texture → complete on timers and the
# viewer gets the committed placeholder mesh (app/assets/photogrammetry/)
USE_MOCK_PHOTOGRAMMETRY=false
#MOCK_PHOTOGRAMMETRY_STAGE_DELAY_SECONDS=2.0
PHOTOGRAMMETRY_MAX_IMAGES=150
PHOTOGRAMMETRY_SAMPLE_PREFIX=samples/photogrammetry/
# ECS task family of the photogrammetry worker; leave empty until it is deployed (confirm → 503)
GPU_PHOTOGRAMMETRY_TASK_FAMILY=
```

- [ ] **Step 6: Run tests**

Run: `cd chat-api && uv run pytest tests/unit/test_photogrammetry_model.py -q`
Expected: 2 passed.

Run: `cd chat-api && uv run pytest tests/unit -q`
Expected: all pass (nothing else touched).

- [ ] **Step 7: Commit**

```bash
git add chat-api/app/models/photogrammetry.py chat-api/app/models/__init__.py \
  chat-api/app/db/migrations/env.py chat-api/app/db/migrations/versions/l2m3n4o5p6q7_add_photogrammetry_jobs.py \
  chat-api/app/config.py chat-api/.env.example chat-api/tests/unit/test_photogrammetry_model.py
git commit -m "feat(api): photogrammetry_jobs model, migration and settings"
```

---

### Task 2: Schemas, exceptions, repository

**Files:**
- Create: `chat-api/app/schemas/photogrammetry.py`
- Create: `chat-api/app/repositories/photogrammetry.py`
- Modify: `chat-api/app/core/exceptions.py` (after `AudioUploadMissing`)
- Test: `chat-api/tests/unit/repositories/test_photogrammetry_repository.py`, `chat-api/tests/unit/test_photogrammetry_schemas.py`

**Interfaces:**
- Consumes: `PhotogrammetryJob` (Task 1).
- Produces:
  - `schemas.photogrammetry`: `MIN_IMAGES = 5`, `ALLOWED_EXTENSIONS = {"jpg","jpeg","png"}`, `JobCreateRequest(name: str|None, filenames: list[str])`, `UploadTarget(filename, key, url)`, `JobCreateResponse(job_id, uploads)`, `JobStatusResponse(job_id, name, status, stage, image_count, preview_url, error_message, mock, created_at, updated_at, completed_at, worker_state, estimated_wait_seconds, gpu_notice)`, `JobListResponse(items, next_cursor)`, `SampleJobResponse(job_id)`, `MeshUrlResponse(url, expires_at)`, helper `extension_of(filename) -> str`.
  - `core.exceptions`: `UploadIncomplete` (409), `WorkerNotDeployed` (503), `ImageCountOutOfRange` (422).
  - `PhotogrammetryRepository(db)`: `create_job(job_id, user_id, name, image_count, input_prefix) -> PhotogrammetryJob`, `get_job(job_id, user_id) -> PhotogrammetryJob|None`, `count_active_jobs(user_id) -> int`, `update_job_status(job_id, status, *, stage=None, mesh_s3_key=None, preview_s3_key=None, error_message=None) -> None`, `list_jobs(user_id, cursor, limit) -> tuple[list, str|None]`, `delete_job(job_id) -> None`.

- [ ] **Step 1: Write the failing tests**

`chat-api/tests/unit/test_photogrammetry_schemas.py`:
```python
import pytest
from pydantic import ValidationError

from app.schemas.photogrammetry import MIN_IMAGES, JobCreateRequest, extension_of


def test_extension_of_lowercases_and_strips():
    assert extension_of("IMG_0001.JPG") == "jpg"
    assert extension_of("a.b.jpeg") == "jpeg"
    assert extension_of("noext") == ""


def test_create_request_rejects_fewer_than_min_images():
    with pytest.raises(ValidationError):
        JobCreateRequest(filenames=[f"{i}.jpg" for i in range(MIN_IMAGES - 1)])


def test_create_request_rejects_unsupported_extension():
    with pytest.raises(ValidationError) as exc:
        JobCreateRequest(filenames=[f"{i}.jpg" for i in range(4)] + ["notes.txt"])
    assert "notes.txt" in str(exc.value)


def test_create_request_accepts_mixed_case_extensions():
    req = JobCreateRequest(filenames=["a.JPG", "b.png", "c.jpeg", "d.jpg", "e.PNG"])
    assert len(req.filenames) == 5
    assert req.name is None
```

`chat-api/tests/unit/repositories/test_photogrammetry_repository.py`:
```python
"""PhotogrammetryRepository — statement shape / mutation verified against a mocked AsyncSession."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.repositories.photogrammetry import PhotogrammetryRepository


def make_repo(scalar=0, one_or_none=None):
    db = MagicMock()
    result = MagicMock()
    result.scalar_one = MagicMock(return_value=scalar)
    result.scalar_one_or_none = MagicMock(return_value=one_or_none)
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    return PhotogrammetryRepository(db), db


def compiled(db) -> str:
    stmt = db.execute.await_args.args[0]
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


async def test_create_job_uses_given_id_and_pending_status():
    repo, db = make_repo()
    job_id = uuid4()
    job = await repo.create_job(job_id, "user1", "Scan", 12, f"photogrammetry/user1/{job_id}/input/")
    assert job.id == job_id
    assert job.status == "pending"
    assert job.image_count == 12
    db.add.assert_called_once_with(job)
    db.flush.assert_awaited_once()


async def test_count_active_jobs_counts_pending_queued_processing():
    repo, db = make_repo(scalar=2)
    assert await repo.count_active_jobs("user1") == 2
    sql = compiled(db)
    assert "photogrammetry_jobs" in sql
    for s in ("pending", "queued", "processing"):
        assert f"'{s}'" in sql
    assert "'complete'" not in sql


async def test_update_job_status_sets_stage_keys_and_completed_at():
    job = MagicMock()
    job.completed_at = None
    repo, db = make_repo(one_or_none=job)
    await repo.update_job_status(uuid4(), "processing", stage="dense")
    assert job.status == "processing"
    assert job.stage == "dense"
    assert job.completed_at is None

    await repo.update_job_status(uuid4(), "complete", mesh_s3_key="k/mesh.glb", preview_s3_key="k/preview.png")
    assert job.status == "complete"
    assert job.stage is None
    assert job.mesh_s3_key == "k/mesh.glb"
    assert job.preview_s3_key == "k/preview.png"
    assert job.completed_at is not None


async def test_get_job_scopes_by_user():
    repo, db = make_repo(one_or_none=None)
    assert await repo.get_job(uuid4(), "user1") is None
    sql = compiled(db)
    assert "user_id = 'user1'" in sql
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd chat-api && uv run pytest tests/unit/test_photogrammetry_schemas.py tests/unit/repositories/test_photogrammetry_repository.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Add exceptions**

`chat-api/app/core/exceptions.py` — insert after the `AudioUploadMissing` class:
```python
class ImageCountOutOfRange(AppException):
    status_code = 422
    detail = "Image count out of range"


class UploadIncomplete(AppException):
    status_code = 409
    detail = "Not every image has been uploaded yet"


class WorkerNotDeployed(AppException):
    status_code = 503
    detail = "photogrammetry worker not deployed"
```

- [ ] **Step 4: Write the schemas**

`chat-api/app/schemas/photogrammetry.py`:
```python
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

MIN_IMAGES = 5
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}


def extension_of(filename: str) -> str:
    """Lower-cased extension without the dot; '' when there is none."""
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


class JobCreateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    filenames: List[str] = Field(..., min_length=MIN_IMAGES)

    @field_validator("filenames")
    @classmethod
    def _supported_images(cls, filenames: List[str]) -> List[str]:
        bad = [f for f in filenames if extension_of(f) not in ALLOWED_EXTENSIONS]
        if bad:
            raise ValueError(f"unsupported image type: {', '.join(bad[:3])}")
        return filenames


class UploadTarget(BaseModel):
    filename: str
    key: str
    url: str


class JobCreateResponse(BaseModel):
    job_id: UUID
    uploads: List[UploadTarget]


class JobStatusResponse(BaseModel):
    job_id: UUID
    name: str
    status: str
    stage: Optional[str] = None
    image_count: int
    preview_url: Optional[str] = None
    error_message: Optional[str] = None
    mock: bool = False
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    worker_state: Optional[str] = None
    estimated_wait_seconds: Optional[int] = None
    gpu_notice: Optional[str] = None


class JobListResponse(BaseModel):
    items: List[JobStatusResponse]
    next_cursor: Optional[str] = None


class SampleJobResponse(BaseModel):
    job_id: UUID


class MeshUrlResponse(BaseModel):
    url: str
    expires_at: datetime
```

- [ ] **Step 5: Write the repository**

`chat-api/app/repositories/photogrammetry.py`:
```python
import base64
import json
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.photogrammetry import PhotogrammetryJob

ACTIVE_STATUSES = ("pending", "queued", "processing")


class PhotogrammetryRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_job(
        self, job_id: UUID, user_id: str, name: str, image_count: int, input_prefix: str
    ) -> PhotogrammetryJob:
        job = PhotogrammetryJob(
            id=job_id,
            user_id=user_id,
            name=name,
            status="pending",
            image_count=image_count,
            input_prefix=input_prefix,
        )
        self.db.add(job)
        await self.db.flush()
        return job

    async def get_job(self, job_id: UUID, user_id: str) -> Optional[PhotogrammetryJob]:
        result = await self.db.execute(
            select(PhotogrammetryJob).where(
                PhotogrammetryJob.id == job_id,
                PhotogrammetryJob.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def count_active_jobs(self, user_id: str) -> int:
        result = await self.db.execute(
            select(func.count()).where(
                PhotogrammetryJob.user_id == user_id,
                PhotogrammetryJob.status.in_(ACTIVE_STATUSES),
            )
        )
        return result.scalar_one()

    async def update_job_status(
        self,
        job_id: UUID,
        status: str,
        *,
        stage: Optional[str] = None,
        mesh_s3_key: Optional[str] = None,
        preview_s3_key: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        result = await self.db.execute(
            select(PhotogrammetryJob).where(PhotogrammetryJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return
        job.status = status
        job.stage = stage if status == "processing" else None
        if mesh_s3_key is not None:
            job.mesh_s3_key = mesh_s3_key
        if preview_s3_key is not None:
            job.preview_s3_key = preview_s3_key
        if error_message is not None:
            job.error_message = error_message
        if status == "complete":
            job.completed_at = datetime.now(timezone.utc)

    async def list_jobs(
        self, user_id: str, cursor: Optional[str], limit: int
    ) -> tuple[List[PhotogrammetryJob], Optional[str]]:
        query = select(PhotogrammetryJob).where(PhotogrammetryJob.user_id == user_id)
        if cursor:
            cursor_data = json.loads(base64.b64decode(cursor).decode())
            cursor_dt = datetime.fromisoformat(cursor_data["created_at"])
            cursor_id = UUID(cursor_data["id"])
            query = query.where(
                or_(
                    PhotogrammetryJob.created_at < cursor_dt,
                    and_(
                        PhotogrammetryJob.created_at == cursor_dt,
                        PhotogrammetryJob.id < cursor_id,
                    ),
                )
            )
        query = (
            query.order_by(PhotogrammetryJob.created_at.desc(), PhotogrammetryJob.id.desc())
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
            select(PhotogrammetryJob).where(PhotogrammetryJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job:
            await self.db.delete(job)
```

- [ ] **Step 6: Run tests**

Run: `cd chat-api && uv run pytest tests/unit/test_photogrammetry_schemas.py tests/unit/repositories/test_photogrammetry_repository.py -q`
Expected: 8 passed.

- [ ] **Step 7: Commit**

```bash
git add chat-api/app/schemas/photogrammetry.py chat-api/app/repositories/photogrammetry.py \
  chat-api/app/core/exceptions.py chat-api/tests/unit/test_photogrammetry_schemas.py \
  chat-api/tests/unit/repositories/test_photogrammetry_repository.py
git commit -m "feat(api): photogrammetry schemas, repository and error types"
```

---

### Task 3: Storage helpers and the dev sink serving files

**Files:**
- Modify: `chat-api/app/services/audio_storage.py` — all three classes
- Modify: `chat-api/app/api/v1/transcribe/dev.py` — GET sink
- Modify: `chat-api/app/api/v1/transcribe/__init__.py` — registration condition
- Test: `chat-api/tests/unit/services/test_audio_storage_download.py`, `chat-api/tests/unit/api/test_dev_sink.py`

**Interfaces:**
- Produces: `generate_presigned_download_url(s3_key: str, ttl_seconds: int = 900) -> str` on `AudioStorageService`, `MockAudioStorageService`, `LocalAudioStorageService`; `write_object(s3_key: str, data: bytes) -> None` on `LocalAudioStorageService` (writes under its root) and `MockAudioStorageService` (no-op). `GET /api/v1/transcribe/dev-upload/{path}` returns the file's bytes with a guessed content type when it exists under `LOCAL_STORAGE_PATH`, else an empty 200 (unchanged behaviour for transcribe).

- [ ] **Step 1: Write the failing tests**

`chat-api/tests/unit/services/test_audio_storage_download.py`:
```python
from unittest.mock import MagicMock, patch

from app.services.audio_storage import (
    AudioStorageService,
    LocalAudioStorageService,
    MockAudioStorageService,
)


def test_local_download_url_points_at_sink(tmp_path):
    s = LocalAudioStorageService("http://localhost:8000/", str(tmp_path))
    assert (
        s.generate_presigned_download_url("photogrammetry/u/j/output/mesh.glb")
        == "http://localhost:8000/api/v1/transcribe/dev-upload/photogrammetry/u/j/output/mesh.glb"
    )


def test_local_write_object_creates_parents_and_is_visible(tmp_path):
    s = LocalAudioStorageService("http://localhost:8000", str(tmp_path))
    s.write_object("a/b/c.bin", b"xyz")
    assert (tmp_path / "a" / "b" / "c.bin").read_bytes() == b"xyz"
    assert s.object_exists("a/b/c.bin")
    assert s.list_keys_with_prefix("a/b/") == ["a/b/c.bin"]


def test_mock_download_url_and_write_object():
    s = MockAudioStorageService("http://localhost:8000")
    assert s.generate_presigned_download_url("k") == "http://localhost:8000/api/v1/transcribe/dev-upload/k"
    s.write_object("k", b"")  # no-op, must not raise


def test_real_download_url_uses_get_object():
    with patch("app.services.audio_storage.boto3") as boto3:
        settings = MagicMock(aws_region="us-east-1", audio_bucket_name="bucket")
        s = AudioStorageService(settings)
        s.s3.generate_presigned_url = MagicMock(return_value="https://signed")
        assert s.generate_presigned_download_url("k", ttl_seconds=60) == "https://signed"
        s.s3.generate_presigned_url.assert_called_once_with(
            "get_object", Params={"Bucket": "bucket", "Key": "k"}, ExpiresIn=60
        )
```

`chat-api/tests/unit/api/test_dev_sink.py`:
```python
"""The dev-upload sink GET serves a stored file (needed for the mock mesh/preview)."""
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.transcribe import dev


def make_app():
    app = FastAPI()
    app.include_router(dev.router, prefix="/api/v1/transcribe")
    return app


async def test_get_returns_file_bytes_with_content_type(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "mesh.glb").write_bytes(b"glTF")
    with patch.object(dev, "get_settings", return_value=MagicMock(local_storage_path=str(tmp_path))):
        async with AsyncClient(transport=ASGITransport(app=make_app()), base_url="http://t") as ac:
            r = await ac.get("/api/v1/transcribe/dev-upload/x/mesh.glb")
    assert r.status_code == 200
    assert r.content == b"glTF"
    assert r.headers["content-type"].startswith("model/gltf-binary")


async def test_get_missing_file_is_empty_200(tmp_path):
    with patch.object(dev, "get_settings", return_value=MagicMock(local_storage_path=str(tmp_path))):
        async with AsyncClient(transport=ASGITransport(app=make_app()), base_url="http://t") as ac:
            r = await ac.get("/api/v1/transcribe/dev-upload/nope.bin")
    assert r.status_code == 200
    assert r.content == b""


async def test_put_then_get_roundtrip(tmp_path):
    with patch.object(dev, "get_settings", return_value=MagicMock(local_storage_path=str(tmp_path))):
        async with AsyncClient(transport=ASGITransport(app=make_app()), base_url="http://t") as ac:
            await ac.put("/api/v1/transcribe/dev-upload/p/0001.jpg", content=b"\xff\xd8")
            r = await ac.get("/api/v1/transcribe/dev-upload/p/0001.jpg")
    assert r.content == b"\xff\xd8"
    assert r.headers["content-type"] == "image/jpeg"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd chat-api && uv run pytest tests/unit/services/test_audio_storage_download.py tests/unit/api/test_dev_sink.py -q`
Expected: FAIL — `AttributeError: … has no attribute 'generate_presigned_download_url'`; the sink GET returns empty bodies.

- [ ] **Step 3: Add the storage helpers**

In `chat-api/app/services/audio_storage.py`:

`AudioStorageService` — insert after `generate_presigned_upload_url`:
```python
    def generate_presigned_download_url(self, s3_key: str, ttl_seconds: int = 900) -> str:
        """Returns a pre-signed GET URL for direct browser download."""
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": s3_key},
            ExpiresIn=ttl_seconds,
        )
```

`MockAudioStorageService` — insert after `generate_presigned_upload_url`:
```python
    def generate_presigned_download_url(self, s3_key: str, ttl_seconds: int = 900) -> str:
        return f"{self._base_url}/api/v1/transcribe/dev-upload/{s3_key}"

    def write_object(self, s3_key: str, data: bytes) -> None:
        pass
```

`LocalAudioStorageService` — insert after `generate_presigned_upload_url`:
```python
    def generate_presigned_download_url(self, s3_key: str, ttl_seconds: int = 900) -> str:
        return f"{self._base_url}/api/v1/transcribe/dev-upload/{s3_key}"

    def write_object(self, s3_key: str, data: bytes) -> None:
        dest = self._root / s3_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
```

- [ ] **Step 4: Make the sink GET serve files**

Replace `chat-api/app/api/v1/transcribe/dev.py` wholesale:
```python
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Request, Response

from app.config import get_settings

router = APIRouter()

mimetypes.add_type("model/gltf-binary", ".glb")


@router.put("/dev-upload/{path:path}", status_code=200)
async def dev_upload_sink(path: str, request: Request) -> Response:
    """Accepts a PUT body and writes it to LOCAL_STORAGE_PATH so dev_worker.py can read it.
    Acts as an S3 replacement for mock mode; the browser's presigned-URL upload succeeds
    and the file is available on disk for downstream processing."""
    body = await request.body()
    settings = get_settings()
    dest = Path(settings.local_storage_path) / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return Response(status_code=200)


@router.get("/dev-upload/{path:path}", status_code=200)
async def dev_download_sink(path: str) -> Response:
    """Serves a file previously written under LOCAL_STORAGE_PATH (mock mesh/preview/images);
    returns an empty 200 when it does not exist, which is what transcribe's mock relies on."""
    root = Path(get_settings().local_storage_path).resolve()
    target = (root / path).resolve()
    if target.is_file() and root in target.parents:
        media_type, _ = mimetypes.guess_type(target.name)
        return Response(content=target.read_bytes(), media_type=media_type or "application/octet-stream")
    return Response(status_code=200)
```

`chat-api/app/api/v1/transcribe/__init__.py` — replace the `if` block:
```python
_settings = get_settings()
if _settings.use_mock_transcription or _settings.use_mock_photogrammetry:
    from app.api.v1.transcribe import dev
    router.include_router(dev.router)
```

- [ ] **Step 5: Run tests**

Run: `cd chat-api && uv run pytest tests/unit/services/test_audio_storage_download.py tests/unit/api/test_dev_sink.py -q`
Expected: 7 passed.

Run: `cd chat-api && uv run pytest tests/unit -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add chat-api/app/services/audio_storage.py chat-api/app/api/v1/transcribe/dev.py \
  chat-api/app/api/v1/transcribe/__init__.py chat-api/tests/unit/services/test_audio_storage_download.py \
  chat-api/tests/unit/api/test_dev_sink.py
git commit -m "feat(api): presigned download URLs; dev-upload sink serves stored files"
```

---

### Task 4: Sample assets — generator script, photos, placeholder mesh

**Files:**
- Create: `scripts/dev/make-photogrammetry-sample.py`
- Create: `chat-api/app/assets/photogrammetry/images/0001.jpg … 0022.jpg`, `chat-api/app/assets/photogrammetry/mesh.glb`, `chat-api/app/assets/photogrammetry/preview.png`, `chat-api/app/assets/photogrammetry/README.md`
- Test: `chat-api/tests/unit/test_photogrammetry_assets.py`

**Interfaces:**
- Produces: the asset directory the mock service reads (`app/assets/photogrammetry/`): `images/NNNN.jpg` (≥ 5 files, JPEG, no EXIF, long edge ≤ 640), `mesh.glb` (valid GLB: magic `glTF`), `preview.png`.

Neil's photos are at `/home/neil/Pictures/iPhone-XS/Photogrammy/` (22 × `IMG_23xx.jpg`, 3024×4032, Apple EXIF including GPS-capable fields). The script runs with `uv run --with pillow --with trimesh --with numpy python scripts/dev/make-photogrammetry-sample.py …` — none of those are project dependencies and must not become one.

- [ ] **Step 1: Write the failing test**

`chat-api/tests/unit/test_photogrammetry_assets.py`:
```python
"""The committed sample assets are what the mock service serves — keep them small and clean."""
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[2] / "app" / "assets" / "photogrammetry"


def test_images_exist_are_small_and_exif_free():
    images = sorted((ASSETS / "images").glob("*.jpg"))
    assert len(images) >= 5
    assert [p.name for p in images] == [f"{i:04d}.jpg" for i in range(1, len(images) + 1)]
    total = 0
    for p in images:
        with Image.open(p) as im:
            assert im.format == "JPEG"
            assert max(im.size) <= 640
            assert not im.getexif(), f"{p.name} still carries EXIF"
        total += p.stat().st_size
    assert total <= 2_500_000


def test_mesh_is_a_glb_and_preview_is_png():
    glb = (ASSETS / "mesh.glb").read_bytes()
    assert glb[:4] == b"glTF"
    assert len(glb) < 200_000
    with Image.open(ASSETS / "preview.png") as im:
        assert im.format == "PNG"
```

Pillow is not a chat-api dependency; add it to the `dev` extras so this test can run:

`chat-api/pyproject.toml` — in `[project.optional-dependencies] dev`, add `"pillow>=10.0",` then run `cd chat-api && uv lock && uv sync --extra dev`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd chat-api && uv run pytest tests/unit/test_photogrammetry_assets.py -q`
Expected: FAIL — assets directory does not exist.

- [ ] **Step 3: Write the generator script**

`scripts/dev/make-photogrammetry-sample.py`:
```python
#!/usr/bin/env python3
"""Build the committed photogrammetry sample assets for chat-api's mock mode.

Usage (from the repo root; none of these libraries are project dependencies):

  uv run --with pillow --with trimesh --with numpy python scripts/dev/make-photogrammetry-sample.py \
      --photos ~/Pictures/some-folder            # real photos → downscaled, EXIF stripped
  uv run --with pillow --with trimesh --with numpy python scripts/dev/make-photogrammetry-sample.py \
      --synthetic                                # 12 drawn placeholder views instead

Always writes mesh.glb (a small procedural vertex-coloured object) and preview.png.
Prints the one-time `aws s3 sync` line for the shared prod sample set; it never touches AWS.
The repo is public: every image is re-encoded from pixels only, so no EXIF (GPS, device,
timestamps) survives.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageOps

DEFAULT_OUT = Path("chat-api/app/assets/photogrammetry")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic"}


def write_photo(src: Path, dest: Path, max_edge: int, quality: int) -> int:
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)          # bake orientation, then drop the tag
        im = im.convert("RGB")
        im.thumbnail((max_edge, max_edge), Image.LANCZOS)
        clean = Image.new("RGB", im.size)
        clean.putdata(list(im.getdata()))        # pixels only — no info dict, no EXIF
        clean.save(dest, "JPEG", quality=quality, optimize=True)
    return dest.stat().st_size


def synthetic_views(out: Path, count: int, size: int) -> None:
    """Draw a coloured hexagonal prism from `count` angles — obviously fake, exercises the UI."""
    for i in range(count):
        angle = 2 * math.pi * i / count
        im = Image.new("RGB", (size, size), (235, 235, 235))
        d = ImageDraw.Draw(im)
        cx, cy, r = size / 2, size / 2, size * 0.3
        pts = [
            (cx + r * math.cos(angle + k * math.pi / 3), cy + r * 0.5 * math.sin(angle + k * math.pi / 3))
            for k in range(6)
        ]
        top = [(x, y - size * 0.18) for x, y in pts]
        for k in range(6):
            shade = 120 + int(100 * (0.5 + 0.5 * math.cos(angle + k * math.pi / 3)))
            d.polygon([pts[k], pts[(k + 1) % 6], top[(k + 1) % 6], top[k]], fill=(shade, 90, 160))
        d.polygon(top, fill=(240, 200, 80))
        d.text((8, 8), f"synthetic view {i + 1}/{count}", fill=(60, 60, 60))
        im.save(out / f"{i + 1:04d}.jpg", "JPEG", quality=80)


def build_mesh() -> trimesh.Trimesh:
    """A vertex-coloured torus knot-ish object: unmistakably procedural, a few KB as GLB."""
    mesh = trimesh.creation.torus(major_radius=1.0, minor_radius=0.35, major_sections=48, minor_sections=18)
    v = mesh.vertices
    t = (v[:, 2] - v[:, 2].min()) / np.ptp(v[:, 2])
    u = (np.arctan2(v[:, 1], v[:, 0]) + math.pi) / (2 * math.pi)
    colors = np.stack([
        (255 * (0.5 + 0.5 * np.sin(2 * math.pi * u))).astype(np.uint8),
        (255 * t).astype(np.uint8),
        (255 * (0.5 + 0.5 * np.cos(2 * math.pi * u))).astype(np.uint8),
        np.full(len(v), 255, dtype=np.uint8),
    ], axis=1)
    mesh.visual.vertex_colors = colors
    return mesh


def render_preview(mesh: trimesh.Trimesh, dest: Path, size: int = 512) -> None:
    """Painter's-algorithm orthographic render with Pillow — no OpenGL needed."""
    rot = trimesh.transformations.euler_matrix(math.radians(-60), 0, math.radians(30))
    v = trimesh.transform_points(mesh.vertices, rot)
    faces = mesh.faces
    colors = mesh.visual.vertex_colors[:, :3]
    lo, hi = v[:, :2].min(axis=0), v[:, :2].max(axis=0)
    scale = (size * 0.8) / max(hi - lo)
    xy = (v[:, :2] - lo) * scale + size * 0.1
    xy[:, 1] = size - xy[:, 1]
    depth = v[faces].mean(axis=1)[:, 2]
    im = Image.new("RGB", (size, size), (28, 28, 32))
    d = ImageDraw.Draw(im)
    light = np.array([0.3, 0.5, 0.8])
    normals = mesh.face_normals @ rot[:3, :3].T
    for fi in np.argsort(depth):
        f = faces[fi]
        shade = 0.35 + 0.65 * max(0.0, float(normals[fi] @ light))
        c = tuple(int(x * shade) for x in colors[f].mean(axis=0))
        d.polygon([tuple(xy[i]) for i in f], fill=c)
    d.text((10, size - 22), "placeholder mesh — not reconstructed", fill=(200, 200, 200))
    im.save(dest, "PNG", optimize=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--photos", type=Path, help="folder of phone photos")
    src.add_argument("--synthetic", action="store_true", help="draw placeholder views instead")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--max-edge", type=int, default=640)
    ap.add_argument("--quality", type=int, default=75)
    ap.add_argument("--count", type=int, default=12, help="synthetic view count")
    ap.add_argument("--budget-bytes", type=int, default=2_000_000)
    args = ap.parse_args()

    images = args.out / "images"
    images.mkdir(parents=True, exist_ok=True)
    for old in images.glob("*"):
        old.unlink()

    if args.synthetic:
        synthetic_views(images, args.count, args.max_edge)
        n = args.count
    else:
        photos = sorted(p for p in args.photos.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        if len(photos) < 5:
            print(f"need at least 5 photos, found {len(photos)} in {args.photos}", file=sys.stderr)
            return 1
        total = 0
        for i, p in enumerate(photos, start=1):
            total += write_photo(p, images / f"{i:04d}.jpg", args.max_edge, args.quality)
        n = len(photos)
        print(f"{n} photos → {total / 1e6:.2f} MB")
        if total > args.budget_bytes:
            print(f"WARNING: over the {args.budget_bytes / 1e6:.1f} MB budget — lower --quality or --max-edge",
                  file=sys.stderr)

    mesh = build_mesh()
    mesh.export(args.out / "mesh.glb")
    render_preview(mesh, args.out / "preview.png")
    print(f"wrote {n} images, mesh.glb ({(args.out / 'mesh.glb').stat().st_size // 1024} KB), preview.png → {args.out}")
    print("\nOne-time upload of the shared prod sample set (run it yourself with your admin profile):")
    print(f"  aws s3 sync {images} s3://<audio-bucket>/samples/photogrammetry/images/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Generate the assets from Neil's photos**

Run from the repo root:
```bash
uv run --with pillow --with trimesh --with numpy python scripts/dev/make-photogrammetry-sample.py \
  --photos /home/neil/Pictures/iPhone-XS/Photogrammy
```
Expected: `22 photos → ~1.5–2.0 MB`, `wrote 22 images, mesh.glb (… KB), preview.png`. If the WARNING prints, re-run with `--quality 70`. If the folder is unavailable on the machine running this task, run with `--synthetic` instead and say so in the commit message — the real set replaces it later with the same command.

Then verify the EXIF is gone independently of the test:
```bash
file chat-api/app/assets/photogrammetry/images/0001.jpg
```
Expected: no `Exif` in the output.

- [ ] **Step 5: Add the asset README**

`chat-api/app/assets/photogrammetry/README.md`:
```markdown
# Photogrammetry sample assets

Served by `LocalPhotogrammetryService` (`USE_MOCK_PHOTOGRAMMETRY=true`) and by `POST /jobs/sample`.

- `images/NNNN.jpg` — a real phone photo set, downscaled to 640 px, **all EXIF stripped**.
- `mesh.glb`, `preview.png` — a procedural placeholder. It is **not** reconstructed from the photos;
  the API marks every mock result `mock: true` and the UI says so.

Regenerate with `scripts/dev/make-photogrammetry-sample.py` (see its docstring).
```

- [ ] **Step 6: Run tests**

Run: `cd chat-api && uv run pytest tests/unit/test_photogrammetry_assets.py -q`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add scripts/dev/make-photogrammetry-sample.py chat-api/app/assets/photogrammetry chat-api/pyproject.toml chat-api/uv.lock \
  chat-api/tests/unit/test_photogrammetry_assets.py
git commit -m "feat(api): photogrammetry sample assets (EXIF-stripped photo set, placeholder GLB) + generator script"
```

---

### Task 5: `PhotogrammetryService` (real path)

**Files:**
- Create: `chat-api/app/services/photogrammetry_service.py`
- Test: `chat-api/tests/unit/services/test_photogrammetry_service.py`

**Interfaces:**
- Consumes: `PhotogrammetryRepository` (Task 2), storage helpers (Task 3), `GpuController.ensure_worker(reason, user_id)` / `get_state()` and `GpuCapExceeded` from `app.services.gpu_controller`.
- Produces: `PhotogrammetryService(repo, storage, settings, gpu=None)` with `is_mock = False` and async methods `create_job(user_id, request) -> JobCreateResponse`, `confirm_job(user_id, job_id) -> None`, `get_job_status(user_id, job_id) -> JobStatusResponse`, `list_jobs(user_id, cursor, limit) -> JobListResponse`, `delete_job(user_id, job_id) -> None`, `get_mesh_url(user_id, job_id) -> MeshUrlResponse`, `create_sample_job(user_id) -> SampleJobResponse`; module constants `DOWNLOAD_TTL_SECONDS = 900`, `STAGES`.

- [ ] **Step 1: Write the failing tests**

`chat-api/tests/unit/services/test_photogrammetry_service.py`:
```python
"""Unit tests for PhotogrammetryService — no real DB, S3 or ECS."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import (
    ConcurrentJobLimitExceeded,
    ConflictError,
    ImageCountOutOfRange,
    NotFoundError,
    UploadIncomplete,
    WorkerNotDeployed,
)
from app.schemas.photogrammetry import JobCreateRequest
from app.services.gpu_controller import GpuCapExceeded
from app.services.photogrammetry_service import PhotogrammetryService

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def make_job(**overrides):
    job = MagicMock()
    job.id = overrides.get("id", uuid4())
    job.user_id = "user1"
    job.name = "Scan"
    job.status = overrides.get("status", "pending")
    job.stage = overrides.get("stage")
    job.image_count = overrides.get("image_count", 6)
    job.input_prefix = f"photogrammetry/user1/{job.id}/input/"
    job.mesh_s3_key = overrides.get("mesh_s3_key")
    job.preview_s3_key = overrides.get("preview_s3_key")
    job.error_message = None
    job.created_at = job.updated_at = NOW
    job.completed_at = None
    return job


def make_service(*, active_jobs=0, max_images=150, gpu=None, job=None, keys=None):
    repo = MagicMock()
    repo.count_active_jobs = AsyncMock(return_value=active_jobs)
    repo.create_job = AsyncMock(side_effect=lambda job_id, user_id, name, image_count, input_prefix: make_job(
        id=job_id, image_count=image_count))
    repo.get_job = AsyncMock(return_value=job)
    repo.update_job_status = AsyncMock()
    repo.list_jobs = AsyncMock(return_value=([], None))
    repo.delete_job = AsyncMock()
    repo.db = MagicMock()
    repo.db.commit = AsyncMock()

    storage = MagicMock()
    storage.generate_presigned_upload_url = MagicMock(side_effect=lambda k, ttl_seconds=900: f"https://up/{k}")
    storage.generate_presigned_download_url = MagicMock(side_effect=lambda k, ttl_seconds=900: f"https://dl/{k}")
    storage.list_keys_with_prefix = MagicMock(return_value=keys if keys is not None else [])

    settings = MagicMock()
    settings.max_concurrent_jobs = 3
    settings.photogrammetry_max_images = max_images
    settings.photogrammetry_sample_prefix = "samples/photogrammetry/"

    return PhotogrammetryService(repo, storage, settings, gpu), repo, storage


FILES = ["IMG_1.JPG", "b.png", "c.jpeg", "d.jpg", "e.jpg", "f.jpg"]


class TestCreateJob:
    async def test_429_at_cap(self):
        svc, *_ = make_service(active_jobs=3)
        with pytest.raises(ConcurrentJobLimitExceeded):
            await svc.create_job("user1", JobCreateRequest(filenames=FILES))

    async def test_422_over_max_images(self):
        svc, *_ = make_service(max_images=5)
        with pytest.raises(ImageCountOutOfRange):
            await svc.create_job("user1", JobCreateRequest(filenames=FILES))

    async def test_one_upload_per_file_with_padded_keys(self):
        svc, repo, storage = make_service()
        res = await svc.create_job("user1", JobCreateRequest(name="Mug", filenames=FILES))
        assert len(res.uploads) == 6
        prefix = f"photogrammetry/user1/{res.job_id}/input/"
        assert res.uploads[0].key == f"{prefix}0001.jpg"
        assert res.uploads[1].key == f"{prefix}0002.png"
        assert res.uploads[5].key == f"{prefix}0006.jpg"
        assert res.uploads[0].filename == "IMG_1.JPG"
        assert res.uploads[0].url == f"https://up/{prefix}0001.jpg"
        repo.create_job.assert_awaited_once()
        kwargs = repo.create_job.await_args.kwargs
        assert kwargs["name"] == "Mug" and kwargs["image_count"] == 6 and kwargs["input_prefix"] == prefix

    async def test_default_name_when_omitted(self):
        svc, repo, _ = make_service()
        await svc.create_job("user1", JobCreateRequest(filenames=FILES))
        assert repo.create_job.await_args.kwargs["name"].startswith("Scan ")


class TestConfirmJob:
    async def test_404_unknown(self):
        svc, *_ = make_service(job=None)
        with pytest.raises(NotFoundError):
            await svc.confirm_job("user1", uuid4())

    async def test_409_not_pending(self):
        svc, *_ = make_service(job=make_job(status="queued"))
        with pytest.raises(ConflictError):
            await svc.confirm_job("user1", uuid4())

    async def test_503_when_worker_not_deployed_and_job_stays_pending(self):
        job = make_job()
        svc, repo, _ = make_service(job=job, gpu=None, keys=[f"k{i}" for i in range(6)])
        with pytest.raises(WorkerNotDeployed):
            await svc.confirm_job("user1", job.id)
        repo.update_job_status.assert_not_awaited()

    async def test_409_when_uploads_incomplete(self):
        job = make_job(image_count=6)
        gpu = MagicMock()
        svc, repo, _ = make_service(job=job, gpu=gpu, keys=["a", "b"])
        with pytest.raises(UploadIncomplete):
            await svc.confirm_job("user1", job.id)
        repo.update_job_status.assert_not_awaited()

    async def test_queues_and_ensures_worker(self):
        job = make_job(image_count=6)
        gpu = MagicMock()
        gpu.ensure_worker = AsyncMock()
        svc, repo, storage = make_service(job=job, gpu=gpu, keys=[f"k{i}" for i in range(6)])
        await svc.confirm_job("user1", job.id)
        storage.list_keys_with_prefix.assert_called_once_with(job.input_prefix)
        repo.update_job_status.assert_awaited_once_with(job.id, "queued")
        repo.db.commit.assert_awaited()
        gpu.ensure_worker.assert_awaited_once_with("job", "user1")

    async def test_cap_exceeded_leaves_job_queued(self):
        job = make_job(image_count=6)
        gpu = MagicMock()
        gpu.ensure_worker = AsyncMock(side_effect=GpuCapExceeded("daily cap"))
        svc, repo, _ = make_service(job=job, gpu=gpu, keys=[f"k{i}" for i in range(6)])
        await svc.confirm_job("user1", job.id)   # must not raise
        repo.update_job_status.assert_awaited_once_with(job.id, "queued")


class TestStatusAndMesh:
    async def test_status_includes_preview_url_and_mock_false(self):
        job = make_job(status="complete", preview_s3_key="p/preview.png", mesh_s3_key="p/mesh.glb")
        svc, *_ = make_service(job=job)
        res = await svc.get_job_status("user1", job.id)
        assert res.preview_url == "https://dl/p/preview.png"
        assert res.mock is False
        assert res.name == "Scan" and res.image_count == 6

    async def test_status_resumes_worker_when_off(self):
        job = make_job(status="queued")
        gpu = MagicMock()
        off = MagicMock(worker_state="off", estimated_wait_seconds=180, notice=None)
        gpu.get_state = AsyncMock(return_value=off)
        gpu.ensure_worker = AsyncMock(return_value=MagicMock(worker_state="starting", estimated_wait_seconds=120, notice=None))
        svc, *_ = make_service(job=job, gpu=gpu)
        res = await svc.get_job_status("user1", job.id)
        gpu.ensure_worker.assert_awaited_once_with("resume", "user1")
        assert res.worker_state == "starting"

    async def test_mesh_url_409_until_complete(self):
        svc, *_ = make_service(job=make_job(status="processing"))
        with pytest.raises(ConflictError):
            await svc.get_mesh_url("user1", uuid4())

    async def test_mesh_url_when_complete(self):
        job = make_job(status="complete", mesh_s3_key="p/mesh.glb")
        svc, *_ = make_service(job=job)
        res = await svc.get_mesh_url("user1", job.id)
        assert res.url == "https://dl/p/mesh.glb"
        assert res.expires_at > datetime.now(timezone.utc)

    async def test_delete_404_for_other_user(self):
        svc, repo, _ = make_service(job=None)
        with pytest.raises(NotFoundError):
            await svc.delete_job("user1", uuid4())
        repo.delete_job.assert_not_awaited()


class TestSampleJob:
    async def test_409_when_sample_set_missing(self):
        svc, *_ = make_service(gpu=MagicMock(), keys=[])
        with pytest.raises(ConflictError):
            await svc.create_sample_job("user1")

    async def test_creates_queued_job_from_shared_prefix(self):
        gpu = MagicMock()
        gpu.ensure_worker = AsyncMock()
        svc, repo, storage = make_service(gpu=gpu, keys=[f"samples/photogrammetry/images/{i:04d}.jpg" for i in range(1, 8)])
        res = await svc.create_sample_job("user1")
        kwargs = repo.create_job.await_args.kwargs
        assert kwargs["input_prefix"] == "samples/photogrammetry/images/"
        assert kwargs["image_count"] == 7
        assert kwargs["name"] == "Sample scan"
        repo.update_job_status.assert_awaited_once_with(res.job_id, "queued")
        gpu.ensure_worker.assert_awaited_once_with("job", "user1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd chat-api && uv run pytest tests/unit/services/test_photogrammetry_service.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.photogrammetry_service`.

- [ ] **Step 3: Write the service**

`chat-api/app/services/photogrammetry_service.py`:
```python
"""Photogrammetry jobs: upload a photo set, queue it for the GPU worker, serve the result.

`PhotogrammetryService` is the real path (S3 + ECS via the shared GpuController).
`LocalPhotogrammetryService` (Task 6) is the in-process mock selected by USE_MOCK_PHOTOGRAMMETRY.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

from app.core.exceptions import (
    ConcurrentJobLimitExceeded,
    ConflictError,
    ImageCountOutOfRange,
    NotFoundError,
    UploadIncomplete,
    WorkerNotDeployed,
)
from app.models.photogrammetry import STAGES  # noqa: F401  (re-exported for the mock/tests)
from app.repositories.photogrammetry import PhotogrammetryRepository
from app.schemas.photogrammetry import (
    JobCreateRequest,
    JobCreateResponse,
    JobListResponse,
    JobStatusResponse,
    MeshUrlResponse,
    SampleJobResponse,
    UploadTarget,
    extension_of,
)
from app.services.gpu_controller import GpuCapExceeded

DOWNLOAD_TTL_SECONDS = 900
ACTIVE_FOR_GPU = ("queued", "processing")


def default_job_name(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"Scan {now:%Y-%m-%d %H:%M}"


class PhotogrammetryService:
    is_mock = False

    def __init__(self, repo: PhotogrammetryRepository, storage, settings, gpu=None):
        self._repo = repo
        self._storage = storage
        self._settings = settings
        self._gpu = gpu

    # ── create / confirm ─────────────────────────────────────────────────────

    async def create_job(self, user_id: str, request: JobCreateRequest) -> JobCreateResponse:
        active = await self._repo.count_active_jobs(user_id)
        if active >= self._settings.max_concurrent_jobs:
            raise ConcurrentJobLimitExceeded()
        if len(request.filenames) > self._settings.photogrammetry_max_images:
            raise ImageCountOutOfRange(
                f"at most {self._settings.photogrammetry_max_images} images per scan"
            )
        job_id = uuid4()
        input_prefix = f"photogrammetry/{user_id}/{job_id}/input/"
        await self._repo.create_job(
            job_id=job_id,
            user_id=user_id,
            name=request.name or default_job_name(),
            image_count=len(request.filenames),
            input_prefix=input_prefix,
        )
        uploads = []
        for i, filename in enumerate(request.filenames, start=1):
            key = f"{input_prefix}{i:04d}.{extension_of(filename)}"
            uploads.append(UploadTarget(
                filename=filename,
                key=key,
                url=self._storage.generate_presigned_upload_url(key),
            ))
        return JobCreateResponse(job_id=job_id, uploads=uploads)

    async def confirm_job(self, user_id: str, job_id: UUID) -> None:
        job = await self._get_or_404(user_id, job_id)
        if job.status != "pending":
            raise ConflictError("Job is not in pending state")
        if self._gpu is None:
            raise WorkerNotDeployed()
        uploaded = self._storage.list_keys_with_prefix(job.input_prefix)
        if len(uploaded) < job.image_count:
            raise UploadIncomplete(f"{len(uploaded)} of {job.image_count} images uploaded")
        await self._queue(job.id, user_id)

    async def _queue(self, job_id: UUID, user_id: str) -> None:
        await self._repo.update_job_status(job_id, "queued")
        await self._repo.db.commit()
        try:
            await self._gpu.ensure_worker("job", user_id)
        except GpuCapExceeded:
            pass  # stays queued; the status poll retries via ensure_worker("resume")
        await self._repo.db.commit()

    # ── read ─────────────────────────────────────────────────────────────────

    async def get_job_status(self, user_id: str, job_id: UUID) -> JobStatusResponse:
        job = await self._get_or_404(user_id, job_id)
        gpu_state = None
        if self._gpu is not None and job.status in ACTIVE_FOR_GPU:
            gpu_state = await self._gpu.get_state()
            if gpu_state.worker_state == "off":
                try:
                    gpu_state = await self._gpu.ensure_worker("resume", user_id)
                except GpuCapExceeded as e:
                    gpu_state = gpu_state.model_copy(update={"notice": e.reason})
        return self._to_response(job, gpu_state)

    async def list_jobs(self, user_id: str, cursor: Optional[str], limit: int) -> JobListResponse:
        items, next_cursor = await self._repo.list_jobs(user_id, cursor, limit)
        return JobListResponse(items=[self._to_response(j) for j in items], next_cursor=next_cursor)

    async def get_mesh_url(self, user_id: str, job_id: UUID) -> MeshUrlResponse:
        job = await self._get_or_404(user_id, job_id)
        if job.status != "complete" or not job.mesh_s3_key:
            raise ConflictError("Mesh not yet available")
        return MeshUrlResponse(
            url=self._storage.generate_presigned_download_url(job.mesh_s3_key, ttl_seconds=DOWNLOAD_TTL_SECONDS),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=DOWNLOAD_TTL_SECONDS),
        )

    async def delete_job(self, user_id: str, job_id: UUID) -> None:
        job = await self._get_or_404(user_id, job_id)
        await self._repo.delete_job(job.id)

    # ── sample ───────────────────────────────────────────────────────────────

    async def create_sample_job(self, user_id: str) -> SampleJobResponse:
        active = await self._repo.count_active_jobs(user_id)
        if active >= self._settings.max_concurrent_jobs:
            raise ConcurrentJobLimitExceeded()
        if self._gpu is None:
            raise WorkerNotDeployed()
        prefix = f"{self._settings.photogrammetry_sample_prefix}images/"
        keys = self._storage.list_keys_with_prefix(prefix)
        if not keys:
            raise ConflictError("Sample photo set has not been uploaded")
        job_id = uuid4()
        await self._repo.create_job(
            job_id=job_id, user_id=user_id, name="Sample scan",
            image_count=len(keys), input_prefix=prefix,
        )
        await self._queue(job_id, user_id)
        return SampleJobResponse(job_id=job_id)

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _get_or_404(self, user_id: str, job_id: UUID):
        job = await self._repo.get_job(job_id, user_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        return job

    def _to_response(self, job, gpu_state=None) -> JobStatusResponse:
        preview_url = (
            self._storage.generate_presigned_download_url(job.preview_s3_key, ttl_seconds=DOWNLOAD_TTL_SECONDS)
            if job.preview_s3_key else None
        )
        return JobStatusResponse(
            job_id=job.id,
            name=job.name,
            status=job.status,
            stage=job.stage,
            image_count=job.image_count,
            preview_url=preview_url,
            error_message=job.error_message,
            mock=self.is_mock,
            created_at=job.created_at,
            updated_at=job.updated_at,
            completed_at=job.completed_at,
            worker_state=gpu_state.worker_state if gpu_state else None,
            estimated_wait_seconds=gpu_state.estimated_wait_seconds if gpu_state else None,
            gpu_notice=gpu_state.notice if gpu_state else None,
        )
```

- [ ] **Step 4: Run tests**

Run: `cd chat-api && uv run pytest tests/unit/services/test_photogrammetry_service.py -q`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add chat-api/app/services/photogrammetry_service.py chat-api/tests/unit/services/test_photogrammetry_service.py
git commit -m "feat(api): PhotogrammetryService — create/confirm/status/list/mesh/sample"
```

---

### Task 6: `LocalPhotogrammetryService` (mock)

**Files:**
- Modify: `chat-api/app/services/photogrammetry_service.py` (append)
- Test: `chat-api/tests/unit/services/test_photogrammetry_service.py` (append)

**Interfaces:**
- Consumes: `PhotogrammetryService` (Task 5), `LocalAudioStorageService.write_object` (Task 3), assets (Task 4).
- Produces: `LocalPhotogrammetryService(repo, storage, settings)` with `is_mock = True`; `confirm_job` and `create_sample_job` schedule `_mock_process_job(job_id)`; module constant `ASSET_DIR`.

- [ ] **Step 1: Write the failing tests**

Append to `chat-api/tests/unit/services/test_photogrammetry_service.py`:
```python
import asyncio
from unittest.mock import patch

from app.services import photogrammetry_service as ps
from app.services.photogrammetry_service import ASSET_DIR, LocalPhotogrammetryService


def make_local(*, job=None, active_jobs=0):
    svc, repo, storage = make_service(job=job, active_jobs=active_jobs)
    storage.write_object = MagicMock()
    local = LocalPhotogrammetryService(svc._repo, storage, svc._settings)
    local._settings.mock_photogrammetry_stage_delay_seconds = 0
    return local, repo, storage


class FakeSessionFactory:
    """Stands in for app.db.session.AsyncSessionLocal; records the repo calls the walk makes."""
    def __init__(self, repo):
        self.repo = repo
        self.session = MagicMock()
        self.session.commit = AsyncMock()
        self.session.rollback = AsyncMock()

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *a):
        return False


class TestLocalService:
    async def test_is_mock_flag_reaches_status(self):
        job = make_job(status="complete", preview_s3_key="p/preview.png")
        local, *_ = make_local(job=job)
        res = await local.get_job_status("user1", job.id)
        assert res.mock is True

    async def test_confirm_queues_without_gpu_and_schedules_walk(self):
        job = make_job()
        local, repo, _ = make_local(job=job)
        with patch.object(local, "_mock_process_job", new=AsyncMock()) as walk:
            await local.confirm_job("user1", job.id)
            await asyncio.sleep(0)
        repo.update_job_status.assert_awaited_once_with(job.id, "queued")
        walk.assert_awaited_once_with(job.id)

    async def test_walk_visits_every_stage_then_writes_outputs_and_completes(self):
        job = make_job()
        local, repo, storage = make_local(job=job)
        factory = FakeSessionFactory(repo)
        with patch.object(ps, "PhotogrammetryRepository", return_value=repo), \
             patch("app.db.session.AsyncSessionLocal", factory):
            await local._mock_process_job(job.id)
        calls = [c.args[1:] + (c.kwargs.get("stage"),) for c in repo.update_job_status.await_args_list]
        assert calls[:4] == [
            ("processing", "sfm"), ("processing", "dense"), ("processing", "mesh"), ("processing", "texture"),
        ]
        final = repo.update_job_status.await_args_list[-1]
        assert final.args[1] == "complete"
        assert final.kwargs["mesh_s3_key"] == f"photogrammetry/user1/{job.id}/output/mesh.glb"
        assert final.kwargs["preview_s3_key"] == f"photogrammetry/user1/{job.id}/output/preview.png"
        written = {c.args[0] for c in storage.write_object.call_args_list}
        assert written == {final.kwargs["mesh_s3_key"], final.kwargs["preview_s3_key"]}
        assert factory.session.commit.await_count >= 5

    async def test_sample_copies_assets_into_sink_and_queues(self):
        local, repo, storage = make_local()
        with patch.object(local, "_mock_process_job", new=AsyncMock()) as walk:
            res = await local.create_sample_job("user1")
            await asyncio.sleep(0)
        n = len(list((ASSET_DIR / "images").glob("*.jpg")))
        assert n >= 5
        assert storage.write_object.call_count == n
        first_key = storage.write_object.call_args_list[0].args[0]
        assert first_key == f"photogrammetry/user1/{res.job_id}/input/0001.jpg"
        kwargs = repo.create_job.await_args.kwargs
        assert kwargs["image_count"] == n and kwargs["name"] == "Sample scan"
        repo.update_job_status.assert_awaited_once_with(res.job_id, "queued")
        walk.assert_awaited_once_with(res.job_id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd chat-api && uv run pytest tests/unit/services/test_photogrammetry_service.py -q -k Local`
Expected: FAIL — `ImportError: cannot import name 'LocalPhotogrammetryService'`.

- [ ] **Step 3: Append the mock service**

Append to `chat-api/app/services/photogrammetry_service.py` (add `import asyncio` and `from pathlib import Path` to the imports at the top):
```python
ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "photogrammetry"


class LocalPhotogrammetryService(PhotogrammetryService):
    """Mock for local dev (USE_MOCK_PHOTOGRAMMETRY=true): real Postgres, no S3, no ECS.

    confirm_job trusts the dev-upload sink and walks the job
    queued → processing(sfm → dense → mesh → texture) → complete on timers, then copies the
    committed placeholder mesh/preview into the sink under the job's output keys.
    """
    is_mock = True

    def __init__(self, repo: PhotogrammetryRepository, storage, settings):
        super().__init__(repo, storage, settings, gpu=None)

    async def confirm_job(self, user_id: str, job_id: UUID) -> None:
        job = await self._get_or_404(user_id, job_id)
        if job.status != "pending":
            raise ConflictError("Job is not in pending state")
        await self._repo.update_job_status(job.id, "queued")
        await self._repo.db.commit()
        asyncio.create_task(self._mock_process_job(job.id))

    async def create_sample_job(self, user_id: str) -> SampleJobResponse:
        active = await self._repo.count_active_jobs(user_id)
        if active >= self._settings.max_concurrent_jobs:
            raise ConcurrentJobLimitExceeded()
        job_id = uuid4()
        input_prefix = f"photogrammetry/{user_id}/{job_id}/input/"
        images = sorted((ASSET_DIR / "images").glob("*.jpg"))
        for i, path in enumerate(images, start=1):
            self._storage.write_object(f"{input_prefix}{i:04d}.jpg", path.read_bytes())
        await self._repo.create_job(
            job_id=job_id, user_id=user_id, name="Sample scan",
            image_count=len(images), input_prefix=input_prefix,
        )
        await self._repo.update_job_status(job_id, "queued")
        await self._repo.db.commit()
        asyncio.create_task(self._mock_process_job(job_id))
        return SampleJobResponse(job_id=job_id)

    async def _mock_process_job(self, job_id: UUID) -> None:
        import app.db.session as db_session

        delay = self._settings.mock_photogrammetry_stage_delay_seconds

        async def set_status(status: str, **kwargs) -> Optional[str]:
            async with db_session.AsyncSessionLocal() as session:
                try:
                    repo = PhotogrammetryRepository(session)
                    await repo.update_job_status(job_id, status, **kwargs)
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        await asyncio.sleep(delay)
        for stage in STAGES:
            await set_status("processing", stage=stage)
            await asyncio.sleep(delay)

        async with db_session.AsyncSessionLocal() as session:
            job = await PhotogrammetryRepository(session).get_job_any(job_id)
        output_prefix = job.input_prefix.rsplit("input/", 1)[0] + "output/"
        mesh_key = f"{output_prefix}mesh.glb"
        preview_key = f"{output_prefix}preview.png"
        self._storage.write_object(mesh_key, (ASSET_DIR / "mesh.glb").read_bytes())
        self._storage.write_object(preview_key, (ASSET_DIR / "preview.png").read_bytes())
        await set_status("complete", mesh_s3_key=mesh_key, preview_s3_key=preview_key)
```

The walk needs the job row without a user id. Add to `PhotogrammetryRepository` (Task 2 file), after `get_job`:
```python
    async def get_job_any(self, job_id: UUID) -> Optional[PhotogrammetryJob]:
        """Lookup by id only — for background tasks that have no user context."""
        result = await self.db.execute(
            select(PhotogrammetryJob).where(PhotogrammetryJob.id == job_id)
        )
        return result.scalar_one_or_none()
```
and in the test's `make_service`, add `repo.get_job_any = AsyncMock(side_effect=lambda job_id: job)` next to `repo.get_job`.

Note the sample job's `input_prefix` in mock mode is the *job's own* prefix (assets copied in), not the shared sample prefix — so `output/` lands beside it and the sink can serve it. The real service uses the shared prefix because the worker writes outputs under the job prefix regardless (the worker spec fixes that; not this plan's concern).

- [ ] **Step 4: Run tests**

Run: `cd chat-api && uv run pytest tests/unit/services/test_photogrammetry_service.py tests/unit/repositories -q`
Expected: all pass (21 in the service file).

- [ ] **Step 5: Commit**

```bash
git add chat-api/app/services/photogrammetry_service.py chat-api/app/repositories/photogrammetry.py \
  chat-api/tests/unit/services/test_photogrammetry_service.py
git commit -m "feat(api): LocalPhotogrammetryService — timed stage walk with placeholder outputs"
```

---

### Task 7: Router, deps, mount, API docs

**Files:**
- Create: `chat-api/app/api/v1/photogrammetry/__init__.py`, `deps.py`, `jobs.py`
- Modify: `chat-api/app/api/v1/router.py`
- Modify: `chat-api/CLAUDE.md` (Commands → Tests list; layout tree; env table; Mock notes)
- Test: `chat-api/tests/unit/api/test_photogrammetry_jobs.py`, `chat-api/tests/unit/api/test_photogrammetry_deps.py`

**Interfaces:**
- Consumes: services (Tasks 5–6), `get_current_user`, `get_db`, `gpu_deps._get_cost_client`, `EcsWorkerLauncher`, `GpuController`, `GpuSessionRepository`.
- Produces: `/api/v1/photogrammetry/jobs…` endpoints per spec §1; `deps.get_photogrammetry_service(db) -> PhotogrammetryService`; `deps._launchers` cache keyed on `(gpu_cluster, gpu_photogrammetry_task_family, gpu_capacity_provider, aws_region)`.

- [ ] **Step 1: Write the failing tests**

`chat-api/tests/unit/api/test_photogrammetry_jobs.py`:
```python
"""HTTP layer for /api/v1/photogrammetry — service is mocked."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.photogrammetry.deps import get_photogrammetry_service
from app.core.exceptions import (
    ConcurrentJobLimitExceeded,
    ConflictError,
    ImageCountOutOfRange,
    NotFoundError,
    UploadIncomplete,
    WorkerNotDeployed,
)
from app.dependencies import get_current_user
from app.main import app
from app.schemas.photogrammetry import (
    JobCreateResponse,
    JobListResponse,
    JobStatusResponse,
    MeshUrlResponse,
    SampleJobResponse,
    UploadTarget,
)

H = {"Authorization": "Bearer fake"}
FILES = [f"{i}.jpg" for i in range(6)]


def status_response(**over):
    now = datetime.now(timezone.utc)
    base = dict(job_id=uuid4(), name="Scan", status="pending", image_count=6,
                created_at=now, updated_at=now)
    base.update(over)
    return JobStatusResponse(**base)


def make_mock_service():
    svc = AsyncMock()
    svc.create_job = AsyncMock(return_value=JobCreateResponse(
        job_id=uuid4(), uploads=[UploadTarget(filename=f, key=f"k/{i:04d}.jpg", url="https://up") for i, f in enumerate(FILES, 1)]))
    svc.confirm_job = AsyncMock(return_value=None)
    svc.list_jobs = AsyncMock(return_value=JobListResponse(items=[status_response()], next_cursor=None))
    svc.get_job_status = AsyncMock(return_value=status_response(status="processing", stage="dense"))
    svc.delete_job = AsyncMock(return_value=None)
    svc.get_mesh_url = AsyncMock(return_value=MeshUrlResponse(url="https://dl/mesh.glb", expires_at=datetime.now(timezone.utc)))
    svc.create_sample_job = AsyncMock(return_value=SampleJobResponse(job_id=uuid4()))
    return svc


@pytest.fixture
async def client():
    svc = make_mock_service()
    app.dependency_overrides[get_photogrammetry_service] = lambda: svc
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user1"}
    with patch("app.db.session.init_db", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, svc
    app.dependency_overrides.clear()


class TestCreate:
    async def test_202_with_one_upload_per_file(self, client):
        ac, svc = client
        r = await ac.post("/api/v1/photogrammetry/jobs", json={"name": "Mug", "filenames": FILES}, headers=H)
        assert r.status_code == 202
        assert len(r.json()["uploads"]) == 6
        assert svc.create_job.await_args.args[0] == "user1"

    async def test_422_too_few_files(self, client):
        ac, _ = client
        r = await ac.post("/api/v1/photogrammetry/jobs", json={"filenames": FILES[:4]}, headers=H)
        assert r.status_code == 422

    async def test_422_bad_extension(self, client):
        ac, _ = client
        r = await ac.post("/api/v1/photogrammetry/jobs", json={"filenames": FILES[:5] + ["x.gif"]}, headers=H)
        assert r.status_code == 422

    async def test_422_over_max(self, client):
        ac, svc = client
        svc.create_job.side_effect = ImageCountOutOfRange()
        r = await ac.post("/api/v1/photogrammetry/jobs", json={"filenames": FILES}, headers=H)
        assert r.status_code == 422

    async def test_429_at_cap(self, client):
        ac, svc = client
        svc.create_job.side_effect = ConcurrentJobLimitExceeded()
        r = await ac.post("/api/v1/photogrammetry/jobs", json={"filenames": FILES}, headers=H)
        assert r.status_code == 429


class TestConfirm:
    async def test_202(self, client):
        ac, svc = client
        jid = uuid4()
        r = await ac.post(f"/api/v1/photogrammetry/jobs/{jid}/confirm", headers=H)
        assert r.status_code == 202
        svc.confirm_job.assert_awaited_once_with("user1", jid)

    @pytest.mark.parametrize("exc,code", [
        (UploadIncomplete(), 409), (WorkerNotDeployed(), 503),
        (ConflictError("x"), 409), (NotFoundError("x"), 404),
    ])
    async def test_error_mapping(self, client, exc, code):
        ac, svc = client
        svc.confirm_job.side_effect = exc
        r = await ac.post(f"/api/v1/photogrammetry/jobs/{uuid4()}/confirm", headers=H)
        assert r.status_code == code


class TestRead:
    async def test_list(self, client):
        ac, _ = client
        r = await ac.get("/api/v1/photogrammetry/jobs", headers=H)
        assert r.status_code == 200
        assert r.json()["items"][0]["mock"] is False

    async def test_status_carries_stage(self, client):
        ac, _ = client
        r = await ac.get(f"/api/v1/photogrammetry/jobs/{uuid4()}", headers=H)
        assert r.status_code == 200
        assert r.json()["stage"] == "dense"

    async def test_status_404(self, client):
        ac, svc = client
        svc.get_job_status.side_effect = NotFoundError("no")
        r = await ac.get(f"/api/v1/photogrammetry/jobs/{uuid4()}", headers=H)
        assert r.status_code == 404

    async def test_mesh_url(self, client):
        ac, _ = client
        r = await ac.get(f"/api/v1/photogrammetry/jobs/{uuid4()}/mesh", headers=H)
        assert r.status_code == 200
        assert r.json()["url"] == "https://dl/mesh.glb"

    async def test_mesh_409_until_complete(self, client):
        ac, svc = client
        svc.get_mesh_url.side_effect = ConflictError("not yet")
        r = await ac.get(f"/api/v1/photogrammetry/jobs/{uuid4()}/mesh", headers=H)
        assert r.status_code == 409

    async def test_delete_204(self, client):
        ac, _ = client
        r = await ac.delete(f"/api/v1/photogrammetry/jobs/{uuid4()}", headers=H)
        assert r.status_code == 204

    async def test_sample_202(self, client):
        ac, _ = client
        r = await ac.post("/api/v1/photogrammetry/jobs/sample", headers=H)
        assert r.status_code == 202
        assert "job_id" in r.json()
```

`chat-api/tests/unit/api/test_photogrammetry_deps.py`:
```python
"""Service selection: mock vs real, and the real path's GPU controller only when deployed."""
from unittest.mock import MagicMock, patch

from app.api.v1.photogrammetry import deps
from app.services.photogrammetry_service import LocalPhotogrammetryService, PhotogrammetryService


def make_settings(**over):
    d = dict(use_mock_photogrammetry=False, mock_upload_base_url="http://localhost:8000",
             local_storage_path="/tmp/x", gpu_controller_enabled=True,
             gpu_cluster="c", gpu_photogrammetry_task_family="photogrammetry-worker",
             gpu_capacity_provider="cp", aws_region="us-east-1")
    d.update(over)
    return MagicMock(**d)


def setup_function(_):
    deps._launchers.clear()


def test_mock_flag_selects_local_service():
    with patch.object(deps, "get_settings", return_value=make_settings(use_mock_photogrammetry=True)):
        svc = deps.get_photogrammetry_service(db=MagicMock())
    assert isinstance(svc, LocalPhotogrammetryService)
    assert svc._gpu is None


def test_real_service_without_task_family_has_no_gpu():
    with patch.object(deps, "get_settings", return_value=make_settings(gpu_photogrammetry_task_family="")), \
         patch.object(deps, "AudioStorageService"):
        svc = deps.get_photogrammetry_service(db=MagicMock())
    assert type(svc) is PhotogrammetryService
    assert svc._gpu is None


def test_real_service_with_task_family_builds_cached_launcher():
    s = make_settings()
    with patch.object(deps, "get_settings", return_value=s), \
         patch.object(deps, "AudioStorageService"), \
         patch.object(deps, "EcsWorkerLauncher") as launcher_cls, \
         patch.object(deps.gpu_deps, "_get_cost_client", return_value=MagicMock()):
        svc1 = deps.get_photogrammetry_service(db=MagicMock())
        svc2 = deps.get_photogrammetry_service(db=MagicMock())
    assert svc1._gpu is not None and svc2._gpu is not None
    launcher_cls.assert_called_once_with("c", "photogrammetry-worker", "cp", "us-east-1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd chat-api && uv run pytest tests/unit/api/test_photogrammetry_jobs.py tests/unit/api/test_photogrammetry_deps.py -q`
Expected: FAIL — `ModuleNotFoundError: app.api.v1.photogrammetry`.

- [ ] **Step 3: Write deps**

`chat-api/app/api/v1/photogrammetry/deps.py`:
```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.gpu import deps as gpu_deps
from app.config import get_settings
from app.dependencies import get_db
from app.repositories.gpu import GpuSessionRepository
from app.repositories.photogrammetry import PhotogrammetryRepository
from app.services.audio_storage import AudioStorageService, LocalAudioStorageService
from app.services.ecs_launcher import EcsWorkerLauncher
from app.services.gpu_controller import GpuController
from app.services.photogrammetry_service import LocalPhotogrammetryService, PhotogrammetryService

# Launcher for the *photogrammetry* task family — separate from the transcription one in
# gpu/deps.py, same cluster and capacity provider, same gpu_sessions ledger and caps.
_launchers: dict[tuple, EcsWorkerLauncher] = {}


def _get_launcher(s) -> EcsWorkerLauncher:
    key = (s.gpu_cluster, s.gpu_photogrammetry_task_family, s.gpu_capacity_provider, s.aws_region)
    launcher = _launchers.get(key)
    if launcher is None:
        launcher = _launchers[key] = EcsWorkerLauncher(*key)
    return launcher


def get_photogrammetry_service(db: AsyncSession = Depends(get_db)) -> PhotogrammetryService:
    s = get_settings()
    repo = PhotogrammetryRepository(db)
    if s.use_mock_photogrammetry:
        storage = LocalAudioStorageService(s.mock_upload_base_url, s.local_storage_path)
        return LocalPhotogrammetryService(repo, storage, s)
    gpu = None
    if s.gpu_controller_enabled and s.gpu_photogrammetry_task_family:
        gpu = GpuController(
            GpuSessionRepository(db), _get_launcher(s), s,
            cost_client=gpu_deps._get_cost_client(s),
        )
    return PhotogrammetryService(repo, AudioStorageService(s), s, gpu)
```

- [ ] **Step 4: Write the router**

`chat-api/app/api/v1/photogrammetry/jobs.py`:
```python
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.photogrammetry.deps import get_photogrammetry_service
from app.dependencies import get_current_user
from app.schemas.photogrammetry import (
    JobCreateRequest,
    JobCreateResponse,
    JobListResponse,
    JobStatusResponse,
    MeshUrlResponse,
    SampleJobResponse,
)
from app.services.photogrammetry_service import PhotogrammetryService

router = APIRouter()


@router.post("/jobs/sample", status_code=202, response_model=SampleJobResponse)
async def create_sample_job(
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> SampleJobResponse:
    return await service.create_sample_job(current_user["sub"])


@router.post("/jobs", status_code=202, response_model=JobCreateResponse)
async def create_job(
    body: JobCreateRequest,
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> JobCreateResponse:
    return await service.create_job(current_user["sub"], body)


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    cursor: Optional[str] = None,
    limit: int = Query(default=20, le=100),
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> JobListResponse:
    return await service.list_jobs(current_user["sub"], cursor, limit)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> JobStatusResponse:
    return await service.get_job_status(current_user["sub"], job_id)


@router.post("/jobs/{job_id}/confirm", status_code=202)
async def confirm_job(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> None:
    await service.confirm_job(current_user["sub"], job_id)


@router.get("/jobs/{job_id}/mesh", response_model=MeshUrlResponse)
async def get_mesh_url(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> MeshUrlResponse:
    return await service.get_mesh_url(current_user["sub"], job_id)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> None:
    await service.delete_job(current_user["sub"], job_id)
```

`chat-api/app/api/v1/photogrammetry/__init__.py`:
```python
from fastapi import APIRouter

from app.api.v1.photogrammetry import jobs

router = APIRouter()
router.include_router(jobs.router)
```

`chat-api/app/api/v1/router.py` — add the import and mount after the `gpu_router` lines:
```python
from app.api.v1.photogrammetry import router as photogrammetry_router
…
router.include_router(photogrammetry_router, prefix="/photogrammetry", tags=["photogrammetry"])
```

- [ ] **Step 5: Run tests**

Run: `cd chat-api && uv run pytest tests/unit -q`
Expected: all pass (the two new files add 20 tests).

- [ ] **Step 6: Update `chat-api/CLAUDE.md`**

- Under **Tests**, add:
  ```
  uv run pytest tests/unit/services/test_photogrammetry_service.py -q          # photogrammetry service + mock walk
  uv run pytest tests/unit/api/test_photogrammetry_jobs.py -q                  # photogrammetry endpoint HTTP layer
  ```
- In the layout tree: under `api/v1/` add `photogrammetry/ jobs.py, deps.py`; under `services/` add `photogrammetry_service.py  PhotogrammetryService (real) + LocalPhotogrammetryService (mock)`; under `repositories/` add `photogrammetry.py`; under `models/` add `photogrammetry.py  PhotogrammetryJob`; under `schemas/` add `photogrammetry.py`; add a line `assets/photogrammetry/  sample photo set + placeholder mesh for the mock`.
- In the env table add rows for `USE_MOCK_PHOTOGRAMMETRY`, `MOCK_PHOTOGRAMMETRY_STAGE_DELAY_SECONDS`, `PHOTOGRAMMETRY_MAX_IMAGES`, `PHOTOGRAMMETRY_SAMPLE_PREFIX`, `GPU_PHOTOGRAMMETRY_TASK_FAMILY` with the descriptions from Task 1's `.env.example`.
- Under **Mock / local dev notes** add:
  ```
  - **`USE_MOCK_PHOTOGRAMMETRY=true`** — uses `LocalPhotogrammetryService`. Confirmed jobs walk `queued → processing (sfm → dense → mesh → texture) → complete` with `MOCK_PHOTOGRAMMETRY_STAGE_DELAY_SECONDS` per step, then the placeholder `app/assets/photogrammetry/{mesh.glb,preview.png}` is copied into the dev-upload sink under the job's `output/` keys; every status response carries `mock: true`. `POST /jobs/sample` copies the committed sample photos into the sink and confirms. The `dev-upload` sink is registered when either mock flag is set and its GET serves stored files (the viewer loads the GLB from it).
  ```
- In the **GPU controller** paragraph append: `The photogrammetry router builds its own GpuController bound to GPU_PHOTOGRAMMETRY_TASK_FAMILY (same cluster, capacity provider and gpu_sessions ledger); while that setting is empty, confirm returns 503 "photogrammetry worker not deployed".`

- [ ] **Step 7: Commit**

```bash
git add chat-api/app/api/v1/photogrammetry chat-api/app/api/v1/router.py chat-api/CLAUDE.md \
  chat-api/tests/unit/api/test_photogrammetry_jobs.py chat-api/tests/unit/api/test_photogrammetry_deps.py
git commit -m "feat(api): /api/v1/photogrammetry router, service selection, docs"
```

---

### Task 8: Vue types, API client, store

**Files:**
- Modify: `chat-vue/src/types/index.ts` (append)
- Create: `chat-vue/src/lib/photogrammetryApi.ts`, `chat-vue/src/stores/photogrammetry.ts`

**Interfaces:**
- Consumes: `apiClient` (`@/lib/axios`), `uploadToS3` (`@/lib/transcribeApi`), `WorkerState`.
- Produces: types `PhotogrammetryJobStatus`, `PhotogrammetryStage`, `PhotogrammetryJob`, `UploadTarget`, `PhotogrammetryJobCreateResponse`, `PhotogrammetryJobListResponse`, `MeshUrlResponse`; api functions `createJob(name, filenames)`, `confirmJob(jobId)`, `listJobs(cursor?)`, `getJob(jobId)`, `deleteJob(jobId)`, `createSampleJob()`, `getMeshUrl(jobId)`; store `usePhotogrammetryStore()` exposing `jobs, nextCursor, activeJobId, activeJob, uploadProgress, pollingActive, toasts, meshUrls, loadJobs, submitScan, submitSampleJob, selectJob, deleteJob, fetchMeshUrl, resumePollingForActiveJobs, dismissToast`.

- [ ] **Step 1: Append the types**

Append to `chat-vue/src/types/index.ts`:
```ts
// ── Photogrammetry ────────────────────────────────────────────────────────

export type PhotogrammetryJobStatus = 'pending' | 'queued' | 'processing' | 'complete' | 'failed'
export type PhotogrammetryStage = 'sfm' | 'dense' | 'mesh' | 'texture'

export interface PhotogrammetryJob {
  job_id: string
  name: string
  status: PhotogrammetryJobStatus
  stage: PhotogrammetryStage | null
  image_count: number
  preview_url: string | null
  error_message: string | null
  mock: boolean
  created_at: string
  updated_at: string
  completed_at: string | null
  worker_state?: WorkerState | null
  estimated_wait_seconds?: number | null
  gpu_notice?: string | null
}

export interface UploadTarget {
  filename: string
  key: string
  url: string
}

export interface PhotogrammetryJobCreateResponse {
  job_id: string
  uploads: UploadTarget[]
}

export interface PhotogrammetryJobListResponse {
  items: PhotogrammetryJob[]
  next_cursor: string | null
}

export interface MeshUrlResponse {
  url: string
  expires_at: string
}
```

- [ ] **Step 2: Write the API client**

`chat-vue/src/lib/photogrammetryApi.ts`:
```ts
import { apiClient } from "@/lib/axios"
import type {
  MeshUrlResponse,
  PhotogrammetryJob,
  PhotogrammetryJobCreateResponse,
  PhotogrammetryJobListResponse,
} from "@/types"

export { uploadToS3 } from "@/lib/transcribeApi"

const BASE = "/api/v1/photogrammetry"

export async function createJob(name: string | null, filenames: string[]): Promise<PhotogrammetryJobCreateResponse> {
  const res = await apiClient.post(`${BASE}/jobs`, { name, filenames })
  return res.data
}

export async function confirmJob(jobId: string): Promise<void> {
  await apiClient.post(`${BASE}/jobs/${jobId}/confirm`)
}

export async function listJobs(cursor?: string): Promise<PhotogrammetryJobListResponse> {
  const res = await apiClient.get(`${BASE}/jobs`, { params: { cursor, limit: 20 } })
  return res.data
}

export async function getJob(jobId: string): Promise<PhotogrammetryJob> {
  const res = await apiClient.get(`${BASE}/jobs/${jobId}`)
  return res.data
}

export async function deleteJob(jobId: string): Promise<void> {
  await apiClient.delete(`${BASE}/jobs/${jobId}`)
}

export async function createSampleJob(): Promise<{ job_id: string }> {
  const res = await apiClient.post(`${BASE}/jobs/sample`)
  return res.data
}

export async function getMeshUrl(jobId: string): Promise<MeshUrlResponse> {
  const res = await apiClient.get(`${BASE}/jobs/${jobId}/mesh`)
  return res.data
}
```

- [ ] **Step 3: Write the store**

`chat-vue/src/stores/photogrammetry.ts`:
```ts
import { defineStore } from "pinia"
import { computed, reactive, ref } from "vue"
import axios from "axios"
import * as api from "@/lib/photogrammetryApi"
import type { PhotogrammetryJob } from "@/types"

export interface Toast {
  id: number
  message: string
}

export interface UploadProgress {
  done: number
  total: number
}

const ACTIVE = new Set(["pending", "queued", "processing"])
const POLL_INTERVAL_MS = Number(import.meta.env.VITE_PHOTOGRAMMETRY_POLL_INTERVAL_MS) || 3_000
const POLL_INTERVAL_PAUSED_MS = 60_000
const UPLOAD_CONCURRENCY = 4
let nextToastId = 0

export const usePhotogrammetryStore = defineStore("photogrammetry", () => {
  // ── State ─────────────────────────────────────────────────────────────
  const jobs = ref<PhotogrammetryJob[]>([])
  const nextCursor = ref<string | null>(null)
  const activeJobId = ref<string | null>(null)
  const uploadProgress = ref<UploadProgress | null>(null)
  const meshUrls = ref<Record<string, { url: string; expiresAt: number }>>({})
  const toasts = ref<Toast[]>([])
  const pollingActive = reactive(new Set<string>())
  const pollTimers = new Map<string, ReturnType<typeof setTimeout>>()

  const activeJob = computed(() => jobs.value.find(j => j.job_id === activeJobId.value) ?? null)

  // ── Toasts ────────────────────────────────────────────────────────────
  function dismissToast(id: number): void {
    toasts.value = toasts.value.filter(t => t.id !== id)
  }

  function pushToast(message: string): void {
    const id = nextToastId++
    toasts.value.push({ id, message })
    setTimeout(() => dismissToast(id), 8000)
  }

  // ── Jobs ──────────────────────────────────────────────────────────────
  async function loadJobs(reset = false): Promise<void> {
    if (reset) { jobs.value = []; nextCursor.value = null }
    const res = await api.listJobs(nextCursor.value ?? undefined)
    jobs.value.push(...res.items)
    nextCursor.value = res.next_cursor
  }

  function upsert(job: PhotogrammetryJob): void {
    const idx = jobs.value.findIndex(j => j.job_id === job.job_id)
    if (idx === -1) jobs.value.unshift(job)
    else jobs.value[idx] = job
  }

  function placeholder(job_id: string, name: string, image_count: number, status: PhotogrammetryJob["status"]): PhotogrammetryJob {
    const now = new Date().toISOString()
    return {
      job_id, name, status, stage: null, image_count, preview_url: null, error_message: null,
      mock: false, created_at: now, updated_at: now, completed_at: null,
    }
  }

  /** Create → upload every file (4 at a time) → confirm → poll. Returns the job id. */
  async function submitScan(name: string, files: File[]): Promise<string> {
    const { job_id, uploads } = await api.createJob(name || null, files.map(f => f.name))
    upsert(placeholder(job_id, name, files.length, "pending"))
    activeJobId.value = job_id
    uploadProgress.value = { done: 0, total: uploads.length }
    try {
      let next = 0
      async function worker(): Promise<void> {
        while (next < uploads.length) {
          const i = next++
          await api.uploadToS3(uploads[i].url, files[i])
          if (uploadProgress.value) uploadProgress.value.done++
        }
      }
      await Promise.all(Array.from({ length: Math.min(UPLOAD_CONCURRENCY, uploads.length) }, worker))
      await api.confirmJob(job_id)
      const idx = jobs.value.findIndex(j => j.job_id === job_id)
      if (idx !== -1) jobs.value[idx] = { ...jobs.value[idx], status: "queued" }
      startPolling(job_id)
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : undefined
      pushToast(detail ? `Scan failed: ${detail}` : "Scan failed — upload or confirm error")
      throw err
    } finally {
      uploadProgress.value = null
    }
    return job_id
  }

  async function submitSampleJob(): Promise<string> {
    const { job_id } = await api.createSampleJob()
    upsert(placeholder(job_id, "Sample scan", 0, "queued"))
    activeJobId.value = job_id
    startPolling(job_id)
    return job_id
  }

  function selectJob(jobId: string): void {
    activeJobId.value = jobId
  }

  async function deleteJob(jobId: string): Promise<void> {
    stopPolling(jobId)
    await api.deleteJob(jobId)
    jobs.value = jobs.value.filter(j => j.job_id !== jobId)
    delete meshUrls.value[jobId]
    if (activeJobId.value === jobId) activeJobId.value = null
  }

  /** Presigned GLB URL, cached until 30 s before it expires. */
  async function fetchMeshUrl(jobId: string): Promise<string> {
    const cached = meshUrls.value[jobId]
    if (cached && cached.expiresAt - Date.now() > 30_000) return cached.url
    const res = await api.getMeshUrl(jobId)
    meshUrls.value[jobId] = { url: res.url, expiresAt: new Date(res.expires_at).getTime() }
    return res.url
  }

  // ── Polling ───────────────────────────────────────────────────────────
  function startPolling(jobId: string): void {
    if (pollTimers.has(jobId)) return

    async function tick(): Promise<void> {
      pollingActive.add(jobId)
      let updated: PhotogrammetryJob | null = null
      try {
        updated = await api.getJob(jobId)
      } catch (err) {
        if (axios.isAxiosError(err) && err.response?.status === 404) {
          stopPolling(jobId)
          jobs.value = jobs.value.filter(j => j.job_id !== jobId)
          if (activeJobId.value === jobId) activeJobId.value = null
          return
        }
      } finally {
        pollingActive.delete(jobId)
      }
      if (updated) {
        upsert(updated)
        if (!ACTIVE.has(updated.status)) {
          stopPolling(jobId)
          if (updated.status === "failed") pushToast(`"${updated.name}" failed${updated.error_message ? `: ${updated.error_message}` : ""}`)
          return
        }
      }
      if (pollTimers.has(jobId)) {
        const interval = updated?.worker_state === "off" ? POLL_INTERVAL_PAUSED_MS : POLL_INTERVAL_MS
        pollTimers.set(jobId, setTimeout(tick, interval))
      }
    }

    pollTimers.set(jobId, setTimeout(tick, POLL_INTERVAL_MS))
  }

  function stopPolling(jobId: string): void {
    const t = pollTimers.get(jobId)
    if (t !== undefined) { clearTimeout(t); pollTimers.delete(jobId) }
  }

  function resumePollingForActiveJobs(): void {
    jobs.value.filter(j => ACTIVE.has(j.status)).forEach(j => startPolling(j.job_id))
  }

  return {
    jobs, nextCursor, activeJobId, activeJob, uploadProgress, pollingActive, toasts, meshUrls,
    loadJobs, submitScan, submitSampleJob, selectJob, deleteJob, fetchMeshUrl,
    resumePollingForActiveJobs, dismissToast,
  }
})
```

Add to `chat-vue/src/env.d.ts` inside `ImportMetaEnv`:
```ts
  readonly VITE_PHOTOGRAMMETRY_POLL_INTERVAL_MS?: string
```

- [ ] **Step 4: Type-check**

Run: `cd chat-vue && npm run type-check`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add chat-vue/src/types/index.ts chat-vue/src/lib/photogrammetryApi.ts chat-vue/src/stores/photogrammetry.ts chat-vue/src/env.d.ts
git commit -m "feat(vue): photogrammetry types, API client and store"
```

---

### Task 9: Route, nav tab, view, sidebar, badge, job card

**Files:**
- Modify: `chat-vue/src/router/index.ts`, `chat-vue/src/components/ConversationSidebar.vue:4-19`, `chat-vue/src/components/transcribe/RunSidebar.vue` (nav block)
- Create: `chat-vue/src/views/PhotogrammetryView.vue`, `chat-vue/src/components/photogrammetry/ScanSidebar.vue`, `ScanJobCard.vue`, `ScanStatusBadge.vue`, `ScanDetailView.vue` (skeleton — filled in Tasks 10–11)

**Interfaces:**
- Consumes: store (Task 8), `GpuStatusBar`, `workerStateLabel` (`@/lib/workerState`).
- Produces: route `/photogrammetry`; `ScanSidebar` props `{ showNewJobForm: boolean }` emits `new`, `sample`; `ScanJobCard` props `{ job: PhotogrammetryJob, isActive: boolean }`; `ScanStatusBadge` props `{ status, stage?, workerState?, estimatedWaitSeconds?, isPolling? }`; `ScanDetailView` props `{ showNewJobForm: boolean }` emits `close-new-job-form`.

- [ ] **Step 1: Route**

`chat-vue/src/router/index.ts` — after the `/transcribe` route object add:
```ts
    {
      path: '/photogrammetry',
      name: 'photogrammetry',
      component: () => import('@/views/PhotogrammetryView.vue'),
      meta: { requiresAuth: true },
    },
```

- [ ] **Step 2: Nav tab in both existing sidebars**

In `chat-vue/src/components/ConversationSidebar.vue` and `chat-vue/src/components/transcribe/RunSidebar.vue`, directly after the Transcribe `<RouterLink>…</RouterLink>` inside the `<nav class="flex border-b border-gray-700">`, add:
```vue
      <RouterLink
        to="/photogrammetry"
        class="flex-1 py-2 text-center text-sm font-medium transition-colors"
        :class="$route.path.startsWith('/photogrammetry') ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-gray-400 hover:text-gray-200'"
      >
        Scan
      </RouterLink>
```
Update the comment above each nav from `<!-- Chat / Transcribe nav tabs -->` to `<!-- Chat / Transcribe / Scan nav tabs -->`.

- [ ] **Step 3: Status badge**

`chat-vue/src/components/photogrammetry/ScanStatusBadge.vue`:
```vue
<script setup lang="ts">
import { computed } from "vue"
import type { PhotogrammetryJobStatus, PhotogrammetryStage, WorkerState } from "@/types"
import { workerStateLabel } from "@/lib/workerState"

const props = defineProps<{
  status: PhotogrammetryJobStatus
  stage?: PhotogrammetryStage | null
  workerState?: WorkerState | null
  estimatedWaitSeconds?: number | null
  isPolling?: boolean
}>()

const inFlight = computed(() => props.status === "queued" || props.status === "processing")
const label = computed(() => {
  if (inFlight.value && props.workerState && props.workerState !== "running") {
    return workerStateLabel(props.workerState, props.estimatedWaitSeconds ?? undefined)
  }
  if (props.status === "processing" && props.stage) return `processing · ${props.stage}`
  return props.status
})
const classes = computed(() => ({
  pending: "bg-gray-200 text-gray-700",
  queued: "bg-amber-100 text-amber-800",
  processing: "bg-indigo-100 text-indigo-800",
  complete: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
}[props.status]))
</script>

<template>
  <span
    class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
    :class="classes"
  >
    <span v-if="inFlight" class="h-1.5 w-1.5 rounded-full bg-current" :class="{ 'animate-pulse': isPolling }" />
    {{ label }}
  </span>
</template>
```

- [ ] **Step 4: Job card and sidebar**

`chat-vue/src/components/photogrammetry/ScanJobCard.vue`:
```vue
<script setup lang="ts">
import type { PhotogrammetryJob } from "@/types"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"
import ScanStatusBadge from "./ScanStatusBadge.vue"

const props = defineProps<{
  job: PhotogrammetryJob
  isActive: boolean
}>()

const store = usePhotogrammetryStore()

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  const isToday = date.toDateString() === new Date().toDateString()
  return isToday
    ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" })
}

async function handleDelete(e: Event) {
  e.stopPropagation()
  if (!window.confirm(`Delete "${props.job.name}"?`)) return
  await store.deleteJob(props.job.job_id)
}
</script>

<template>
  <button
    class="group w-full text-left px-3 py-2 rounded-lg text-sm hover:bg-gray-700 transition-colors"
    :class="{ 'bg-gray-700': isActive }"
    @click="store.selectJob(job.job_id)"
  >
    <div class="flex items-center justify-between gap-2">
      <span class="truncate text-gray-200">{{ job.name }}</span>
      <span class="invisible group-hover:visible text-gray-400 hover:text-red-400 text-xs shrink-0" @click.stop="handleDelete">✕</span>
    </div>
    <div class="mt-1 flex items-center justify-between gap-2 text-xs text-gray-400">
      <span>{{ formatDate(job.created_at) }} · {{ job.image_count }} photos</span>
      <ScanStatusBadge
        :status="job.status"
        :stage="job.stage"
        :worker-state="job.worker_state"
        :estimated-wait-seconds="job.estimated_wait_seconds"
        :is-polling="store.pollingActive.has(job.job_id)"
      />
    </div>
  </button>
</template>
```

`chat-vue/src/components/photogrammetry/ScanSidebar.vue`:
```vue
<script setup lang="ts">
import { ref } from "vue"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"
import { useAuthStore } from "@/stores/auth"
import ScanJobCard from "./ScanJobCard.vue"

defineProps<{ showNewJobForm: boolean }>()
const emit = defineEmits<{ new: [] }>()

const store = usePhotogrammetryStore()
const auth = useAuthStore()
const sampleBusy = ref(false)

async function handleSample() {
  if (sampleBusy.value) return
  sampleBusy.value = true
  try { await store.submitSampleJob() } finally { sampleBusy.value = false }
}
</script>

<template>
  <aside class="flex flex-col bg-gray-900 text-white shrink-0 overflow-hidden">
    <!-- Chat / Transcribe / Scan nav tabs -->
    <nav class="flex border-b border-gray-700">
      <RouterLink to="/" class="flex-1 py-2 text-center text-sm font-medium transition-colors"
        :class="$route.path === '/' ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-gray-400 hover:text-gray-200'">Chat</RouterLink>
      <RouterLink to="/transcribe" class="flex-1 py-2 text-center text-sm font-medium transition-colors"
        :class="$route.path.startsWith('/transcribe') ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-gray-400 hover:text-gray-200'">Transcribe</RouterLink>
      <RouterLink to="/photogrammetry" class="flex-1 py-2 text-center text-sm font-medium transition-colors"
        :class="$route.path.startsWith('/photogrammetry') ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-gray-400 hover:text-gray-200'">Scan</RouterLink>
    </nav>

    <div class="p-4 border-b border-gray-700 flex gap-2">
      <button
        class="flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors"
        :class="showNewJobForm ? 'bg-gray-700 text-gray-300 hover:bg-gray-600' : 'bg-indigo-600 hover:bg-indigo-500 text-white'"
        @click="emit('new')"
      >{{ showNewJobForm ? "✕ Cancel" : "+ New scan" }}</button>
      <button
        class="py-2 px-3 rounded-lg text-sm font-medium bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-50"
        :disabled="sampleBusy"
        title="Run the bundled sample photo set"
        @click="handleSample"
      >Sample</button>
    </div>

    <nav class="flex-1 overflow-y-auto p-2 space-y-1">
      <div v-if="store.jobs.length === 0" class="text-gray-400 text-xs p-2">No scans yet</div>
      <ScanJobCard
        v-for="job in store.jobs"
        :key="job.job_id"
        :job="job"
        :is-active="job.job_id === store.activeJobId && !showNewJobForm"
      />
    </nav>

    <div class="p-4 border-t border-gray-700">
      <button class="text-gray-400 hover:text-white text-xs transition-colors" @click="auth.logout()">Sign out</button>
    </div>
  </aside>
</template>
```

- [ ] **Step 5: Detail view skeleton and the page**

`chat-vue/src/components/photogrammetry/ScanDetailView.vue` (skeleton; Tasks 10–11 fill the form and viewer slots):
```vue
<script setup lang="ts">
import { computed } from "vue"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"
import ScanStatusBadge from "./ScanStatusBadge.vue"

defineProps<{ showNewJobForm: boolean }>()
const emit = defineEmits<{ "close-new-job-form": [] }>()

const store = usePhotogrammetryStore()
const job = computed(() => store.activeJob)
</script>

<template>
  <section class="flex flex-col bg-gray-50 text-gray-900">
    <div v-if="showNewJobForm" class="p-6 overflow-y-auto">
      <!-- NewScanForm mounts here in Task 10 -->
      <p class="text-sm text-gray-500">New scan form</p>
    </div>

    <div v-else-if="!job" class="flex flex-1 items-center justify-center text-sm text-gray-500">
      Select a scan or start a new one
    </div>

    <div v-else class="flex flex-1 flex-col overflow-hidden">
      <header class="flex items-center gap-3 border-b border-gray-200 bg-white px-6 py-3">
        <h2 class="truncate text-base font-semibold">{{ job.name }}</h2>
        <ScanStatusBadge :status="job.status" :stage="job.stage" :worker-state="job.worker_state" :estimated-wait-seconds="job.estimated_wait_seconds" />
        <span class="text-xs text-gray-500">{{ job.image_count }} photos</span>
        <span v-if="job.gpu_notice" class="ml-auto text-xs text-amber-700">{{ job.gpu_notice }}</span>
      </header>
      <div class="flex-1 overflow-auto p-6">
        <!-- Task 11: progress / viewer / error -->
        <p v-if="job.status === 'failed'" class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ job.error_message ?? "Reconstruction failed" }}</p>
        <p v-else class="text-sm text-gray-500">{{ job.status }}</p>
      </div>
    </div>
  </section>
</template>
```

`chat-vue/src/views/PhotogrammetryView.vue`:
```vue
<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue"
import ScanSidebar from "@/components/photogrammetry/ScanSidebar.vue"
import ScanDetailView from "@/components/photogrammetry/ScanDetailView.vue"
import GpuStatusBar from "@/components/transcribe/GpuStatusBar.vue"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"

const store = usePhotogrammetryStore()
const showNewJobForm = ref(false)

const SIDEBAR_MIN = 160
const SIDEBAR_MAX = 480
const SIDEBAR_DEFAULT = 256

const sidebarWidth = ref(parseInt(localStorage.getItem("scanSidebarWidth") ?? "") || SIDEBAR_DEFAULT)
const isDragging = ref(false)

function onDrag(e: MouseEvent) {
  sidebarWidth.value = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, e.clientX))
  localStorage.setItem("scanSidebarWidth", String(sidebarWidth.value))
}
function stopDrag() {
  isDragging.value = false
  document.removeEventListener("mousemove", onDrag)
  document.removeEventListener("mouseup", stopDrag)
}
function startDrag() {
  isDragging.value = true
  document.addEventListener("mousemove", onDrag)
  document.addEventListener("mouseup", stopDrag)
}

onUnmounted(stopDrag)
onMounted(async () => {
  await store.loadJobs(true)
  store.resumePollingForActiveJobs()
})
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden">
    <GpuStatusBar />
    <div class="flex min-h-0 flex-1 overflow-hidden" :class="{ 'select-none': isDragging }">
      <ScanSidebar
        :style="{ width: sidebarWidth + 'px' }"
        :show-new-job-form="showNewJobForm"
        @new="showNewJobForm = !showNewJobForm"
      />
      <div
        class="w-1 shrink-0 cursor-col-resize transition-colors hover:bg-indigo-500"
        :class="isDragging ? 'bg-indigo-500' : 'bg-gray-700'"
        @mousedown.prevent="startDrag"
      />
      <ScanDetailView
        class="flex-1 overflow-hidden"
        :show-new-job-form="showNewJobForm"
        @close-new-job-form="showNewJobForm = false"
      />
    </div>

    <Teleport to="body">
      <div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        <div
          v-for="toast in store.toasts"
          :key="toast.id"
          class="flex items-start gap-3 bg-red-700 text-white text-sm rounded-lg shadow-lg px-4 py-3"
        >
          <span class="flex-1">{{ toast.message }}</span>
          <button class="text-white/70 hover:text-white shrink-0" @click="store.dismissToast(toast.id)">✕</button>
        </div>
      </div>
    </Teleport>
  </div>
</template>
```

- [ ] **Step 6: Type-check and build**

Run: `cd chat-vue && npm run type-check && npm run build`
Expected: both clean. (If `vue-tsc` reports the unused `emit` in `ScanDetailView`, that's expected until Task 10 wires it — keep it; the repo's tsconfig does not fail on unused locals.)

- [ ] **Step 7: Commit**

```bash
git add chat-vue/src/router/index.ts chat-vue/src/components/ConversationSidebar.vue \
  chat-vue/src/components/transcribe/RunSidebar.vue chat-vue/src/views/PhotogrammetryView.vue \
  chat-vue/src/components/photogrammetry
git commit -m "feat(vue): /photogrammetry page — Scan tab, sidebar, job cards, status badge"
```

---

### Task 10: Image dropzone and new-scan form (upload flow)

**Files:**
- Create: `chat-vue/src/components/photogrammetry/ImageDropzone.vue`, `NewScanForm.vue`
- Modify: `chat-vue/src/components/photogrammetry/ScanDetailView.vue` (mount the form)

**Interfaces:**
- Consumes: `store.submitScan(name, files)`, `store.uploadProgress`.
- Produces: `ImageDropzone` props `{ min: number, max: number }`, emits `files-changed: [files: File[]]`, exposes nothing; `NewScanForm` emits `submitted`.

- [ ] **Step 1: Dropzone**

`chat-vue/src/components/photogrammetry/ImageDropzone.vue`:
```vue
<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue"

const props = withDefaults(defineProps<{ min?: number; max?: number }>(), { min: 5, max: 150 })
const emit = defineEmits<{ "files-changed": [files: File[]] }>()

const ACCEPT = "image/jpeg,image/png"
const fileInput = ref<HTMLInputElement | null>(null)
const files = ref<File[]>([])
const isDragOver = ref(false)
const thumbs = ref<string[]>([])

const error = computed(() => {
  if (files.value.length === 0) return null
  if (files.value.length < props.min) return `Add at least ${props.min} photos (${files.value.length} so far).`
  if (files.value.length > props.max) return `At most ${props.max} photos (${files.value.length} selected).`
  return null
})
const totalMb = computed(() => (files.value.reduce((s, f) => s + f.size, 0) / 1024 / 1024).toFixed(1))

function isImage(f: File): boolean {
  return f.type === "image/jpeg" || f.type === "image/png" || /\.(jpe?g|png)$/i.test(f.name)
}

function addFiles(list: FileList | File[]) {
  const incoming = Array.from(list).filter(isImage)
  const seen = new Set(files.value.map(f => `${f.name}:${f.size}`))
  files.value = [...files.value, ...incoming.filter(f => !seen.has(`${f.name}:${f.size}`))]
}

function clear() {
  files.value = []
}

function onDrop(e: DragEvent) {
  isDragOver.value = false
  if (e.dataTransfer?.files) addFiles(e.dataTransfer.files)
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files) addFiles(input.files)
  input.value = ""
}

function revokeThumbs() {
  thumbs.value.forEach(u => URL.revokeObjectURL(u))
  thumbs.value = []
}

watch(files, (list) => {
  revokeThumbs()
  thumbs.value = list.slice(0, 12).map(f => URL.createObjectURL(f))
  emit("files-changed", error.value ? [] : list)
})

onUnmounted(revokeThumbs)
</script>

<template>
  <div>
    <div
      class="border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors"
      :class="isDragOver ? 'border-indigo-400 bg-indigo-50' : files.length ? 'border-green-300 bg-green-50 hover:border-green-400' : 'border-gray-300 hover:border-gray-400'"
      @dragover.prevent="isDragOver = true"
      @dragleave="isDragOver = false"
      @drop.prevent="onDrop"
      @click="fileInput?.click()"
    >
      <input ref="fileInput" type="file" :accept="ACCEPT" multiple class="hidden" @change="onFileChange" />
      <div v-if="files.length" class="text-sm text-gray-700">
        <span class="font-medium">{{ files.length }} photos</span>
        <span class="text-gray-400 ml-2">({{ totalMb }} MB)</span>
        <div class="mt-3 grid grid-cols-6 gap-1" @click.stop>
          <img v-for="(src, i) in thumbs" :key="i" :src="src" class="aspect-square w-full rounded object-cover" alt="" />
          <div v-if="files.length > thumbs.length" class="flex aspect-square items-center justify-center rounded bg-gray-200 text-xs text-gray-600">
            +{{ files.length - thumbs.length }}
          </div>
        </div>
        <button class="mt-2 text-xs text-gray-500 hover:text-red-600" @click.stop="clear">Clear</button>
      </div>
      <div v-else class="text-sm text-gray-500">
        <p>Drop photos here or click to browse</p>
        <p class="text-xs text-gray-400 mt-1">JPG or PNG · {{ min }}–{{ max }} photos orbiting one object</p>
      </div>
    </div>
    <p v-if="error" class="mt-1 text-xs text-red-600">{{ error }}</p>
  </div>
</template>
```

- [ ] **Step 2: Form**

`chat-vue/src/components/photogrammetry/NewScanForm.vue`:
```vue
<script setup lang="ts">
import { computed, ref } from "vue"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"
import ImageDropzone from "./ImageDropzone.vue"

const emit = defineEmits<{ submitted: [jobId: string] }>()

const store = usePhotogrammetryStore()

function defaultName(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, "0")
  return `Scan ${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const name = ref(defaultName())
const files = ref<File[]>([])
const submitting = ref(false)
const canSubmit = computed(() => files.value.length > 0 && !submitting.value)

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    const jobId = await store.submitScan(name.value.trim(), files.value)
    emit("submitted", jobId)
  } catch {
    // the store already raised a toast
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <form class="mx-auto max-w-xl space-y-4" @submit.prevent="submit">
    <h2 class="text-base font-semibold">New scan</h2>
    <label class="block text-sm">
      <span class="text-gray-700">Name</span>
      <input v-model="name" type="text" maxlength="200" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" />
    </label>
    <ImageDropzone @files-changed="files = $event" />
    <div class="flex items-center gap-3">
      <button
        type="submit"
        class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        :disabled="!canSubmit"
      >{{ submitting ? "Uploading…" : "Start scan" }}</button>
      <span v-if="store.uploadProgress" class="text-sm text-gray-600">
        Uploading {{ store.uploadProgress.done }}/{{ store.uploadProgress.total }}
      </span>
    </div>
  </form>
</template>
```

- [ ] **Step 3: Mount it in the detail view**

In `ScanDetailView.vue`: add `import NewScanForm from "./NewScanForm.vue"` and replace the placeholder block:
```vue
    <div v-if="showNewJobForm" class="p-6 overflow-y-auto">
      <NewScanForm @submitted="emit('close-new-job-form')" />
    </div>
```

- [ ] **Step 4: Type-check and build**

Run: `cd chat-vue && npm run type-check && npm run build`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add chat-vue/src/components/photogrammetry
git commit -m "feat(vue): multi-image dropzone and new-scan form with concurrent presigned uploads"
```

---

### Task 11: Stage strip, mesh viewer, detail view states

**Files:**
- Modify: `chat-vue/package.json` (dependency), `chat-vue/vite.config.ts` (custom element)
- Create: `chat-vue/src/components/photogrammetry/StageStrip.vue`, `MeshViewer.vue`
- Modify: `chat-vue/src/components/photogrammetry/ScanDetailView.vue`

**Interfaces:**
- Consumes: `store.fetchMeshUrl(jobId)`, `job.preview_url`, `job.mock`.
- Produces: `StageStrip` props `{ status, stage }`; `MeshViewer` props `{ src: string, poster?: string | null, mock: boolean }`.

- [ ] **Step 1: Add the dependency and register the custom element**

Run: `cd chat-vue && npm install @google/model-viewer@^4`

`chat-vue/vite.config.ts` — replace `vue(),` with:
```ts
    vue({ template: { compilerOptions: { isCustomElement: (tag) => tag === 'model-viewer' } } }),
```

- [ ] **Step 2: Stage strip**

`chat-vue/src/components/photogrammetry/StageStrip.vue`:
```vue
<script setup lang="ts">
import { computed } from "vue"
import type { PhotogrammetryJobStatus, PhotogrammetryStage } from "@/types"

const props = defineProps<{ status: PhotogrammetryJobStatus; stage: PhotogrammetryStage | null }>()

const STEPS: { key: PhotogrammetryStage; label: string }[] = [
  { key: "sfm", label: "Cameras (SfM)" },
  { key: "dense", label: "Dense cloud" },
  { key: "mesh", label: "Mesh" },
  { key: "texture", label: "Texture" },
]

const currentIdx = computed(() => {
  if (props.status === "complete") return STEPS.length
  if (props.status !== "processing" || !props.stage) return -1
  return STEPS.findIndex(s => s.key === props.stage)
})
</script>

<template>
  <ol class="flex items-center gap-2 text-xs">
    <li v-for="(s, i) in STEPS" :key="s.key" class="flex items-center gap-2">
      <span
        class="flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-semibold"
        :class="i < currentIdx ? 'border-green-500 bg-green-500 text-white'
              : i === currentIdx ? 'border-indigo-500 bg-indigo-500 text-white animate-pulse'
              : 'border-gray-300 text-gray-400'"
      >{{ i + 1 }}</span>
      <span :class="i <= currentIdx ? 'text-gray-800' : 'text-gray-400'">{{ s.label }}</span>
      <span v-if="i < STEPS.length - 1" class="h-px w-6 bg-gray-300" />
    </li>
  </ol>
</template>
```

- [ ] **Step 3: Mesh viewer**

`chat-vue/src/components/photogrammetry/MeshViewer.vue`:
```vue
<script setup lang="ts">
import "@google/model-viewer"

defineProps<{
  src: string
  poster?: string | null
  mock: boolean
}>()
</script>

<template>
  <div class="flex h-full flex-col">
    <p v-if="mock" class="mb-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
      Placeholder mesh — served by the local mock, not reconstructed from these photos.
    </p>
    <model-viewer
      :src="src"
      :poster="poster ?? undefined"
      camera-controls
      auto-rotate
      shadow-intensity="1"
      alt="Reconstructed mesh"
      class="min-h-[360px] w-full flex-1 rounded-lg bg-gray-900"
    />
  </div>
</template>
```

- [ ] **Step 4: Detail view — progress, viewer, error**

Replace the `<script setup>` and the inner content block of `ScanDetailView.vue`:
```vue
<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"
import ScanStatusBadge from "./ScanStatusBadge.vue"
import StageStrip from "./StageStrip.vue"
import MeshViewer from "./MeshViewer.vue"
import NewScanForm from "./NewScanForm.vue"

defineProps<{ showNewJobForm: boolean }>()
const emit = defineEmits<{ "close-new-job-form": [] }>()

const store = usePhotogrammetryStore()
const job = computed(() => store.activeJob)
const meshUrl = ref<string | null>(null)
const meshError = ref<string | null>(null)

watch(
  [() => job.value?.job_id, () => job.value?.status],
  async ([jobId, status]) => {
    meshUrl.value = null
    meshError.value = null
    if (jobId && status === "complete") {
      try {
        meshUrl.value = await store.fetchMeshUrl(jobId)
      } catch {
        meshError.value = "Could not load the mesh URL"
      }
    }
  },
  { immediate: true },
)
</script>
```
and the body `<div class="flex-1 overflow-auto p-6">…</div>`:
```vue
      <div class="flex-1 overflow-auto p-6">
        <template v-if="job.status === 'failed'">
          <p class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ job.error_message ?? "Reconstruction failed" }}</p>
        </template>

        <template v-else-if="job.status === 'complete'">
          <MeshViewer v-if="meshUrl" :src="meshUrl" :poster="job.preview_url" :mock="job.mock" />
          <p v-else-if="meshError" class="text-sm text-red-600">{{ meshError }}</p>
          <p v-else class="text-sm text-gray-500">Loading mesh…</p>
        </template>

        <template v-else>
          <div class="space-y-4">
            <StageStrip :status="job.status" :stage="job.stage" />
            <p class="text-sm text-gray-600">
              <span v-if="job.status === 'pending'">Waiting for uploads to finish…</span>
              <span v-else-if="job.status === 'queued'">Queued — waiting for a GPU worker.</span>
              <span v-else>Reconstructing…</span>
            </p>
            <img v-if="job.preview_url" :src="job.preview_url" alt="" class="max-h-64 rounded border border-gray-200" />
          </div>
        </template>
      </div>
```

- [ ] **Step 5: Type-check and build**

Run: `cd chat-vue && npm run type-check && npm run build`
Expected: clean. The build output shows a separate chunk for `PhotogrammetryView` containing model-viewer (~1 MB) — acceptable, it is route-lazy.

- [ ] **Step 6: Commit**

```bash
git add chat-vue/package.json chat-vue/package-lock.json chat-vue/vite.config.ts chat-vue/src/components/photogrammetry
git commit -m "feat(vue): stage strip and <model-viewer> mesh viewer on the scan detail view"
```

---

### Task 12: Docs and the end-to-end walkthrough

**Files:**
- Modify: `docs/mock-api.md` (new section before *Key files at a glance*, plus table rows), `chat-vue/CLAUDE.md` (layout, routes, API list), `CLAUDE.md` (runtime flow), `docs/design/photogrammetry-ui-spec.md` (Status line)

- [ ] **Step 1: `docs/mock-api.md`**

Insert before `## Key files at a glance`:
```markdown
## Photogrammetry mock

`USE_MOCK_PHOTOGRAMMETRY=true` in `chat-api/.env` swaps in `LocalPhotogrammetryService`:

- `POST /api/v1/photogrammetry/jobs` returns one dev-upload sink URL per photo; the browser PUTs
  them there (4 at a time), then confirms.
- Confirmed jobs walk `queued → processing (sfm → dense → mesh → texture) → complete`, one
  `MOCK_PHOTOGRAMMETRY_STAGE_DELAY_SECONDS` (default 2 s) per step, then the committed placeholder
  `chat-api/app/assets/photogrammetry/{mesh.glb,preview.png}` is copied into the sink under the job's
  `output/` keys and served back by the sink's GET — `<model-viewer>` loads the GLB from there.
- **Sample** in the sidebar (`POST /jobs/sample`) copies the bundled photo set into the sink and runs
  the same walk, so the page works with nothing uploaded.
- Every status response carries `mock: true`; the viewer labels the mesh as a placeholder.

Regenerate the sample assets with `scripts/dev/make-photogrammetry-sample.py` (see its docstring).
```
Add to the key-files table:
```markdown
| [chat-api/app/services/photogrammetry_service.py](../chat-api/app/services/photogrammetry_service.py) | `LocalPhotogrammetryService` — timed stage walk, placeholder outputs |
| [chat-api/app/assets/photogrammetry/](../chat-api/app/assets/photogrammetry/) | Sample photo set (EXIF-stripped) + placeholder `mesh.glb` / `preview.png` |
| [scripts/dev/make-photogrammetry-sample.py](../scripts/dev/make-photogrammetry-sample.py) | Regenerates those assets from a photo folder (or `--synthetic`) |
```

- [ ] **Step 2: `chat-vue/CLAUDE.md`**

- Routes line: `Four routes: / (ChatView), /transcribe (TranscribeView), /photogrammetry (PhotogrammetryView), /callback (CallbackView)` (plus profile/admin as already listed).
- Layout: add `photogrammetryApi.ts   Photogrammetry API calls (jobs, uploads, mesh URL)` under `lib/`; `photogrammetry.ts   Scan jobs state, concurrent uploads, 3 s polling, presigned mesh URL cache` under `stores/`; `PhotogrammetryView.vue  Scan layout: resizable ScanSidebar + ScanDetailView, GpuStatusBar on top` under `views/`; a `photogrammetry/` block under `components/` listing `ScanSidebar, ScanJobCard, ScanStatusBadge, StageStrip, ImageDropzone, NewScanForm, ScanDetailView, MeshViewer (<model-viewer> web component; registered as a custom element in vite.config.ts)`.
- API section: add **Photogrammetry (`/api/v1/photogrammetry/`):** `POST /jobs {name, filenames[]} → {job_id, uploads[{filename,key,url}]}` · `POST /jobs/{id}/confirm` · `GET /jobs` · `GET /jobs/{id}` · `DELETE /jobs/{id}` · `POST /jobs/sample` · `GET /jobs/{id}/mesh → {url, expires_at}`.
- Notes: `Scan sidebar width is persisted under scanSidebarWidth; job polling every 3 s (VITE_PHOTOGRAMMETRY_POLL_INTERVAL_MS), 60 s while the GPU worker is off; resumes on reload via resumePollingForActiveJobs().`

- [ ] **Step 3: Root `CLAUDE.md`**

In the runtime-flow block, after the `→ SQS → RunTask launches transcription-worker …` lines, add:
```
      → S3 (photo sets under photogrammetry/<user>/<job>/input/) → RunTask photogrammetry worker
                  (not yet built — confirm returns 503 until GPU_PHOTOGRAMMETRY_TASK_FAMILY is set;
                  local dev uses the in-process mock, see docs/mock-api.md)
```

- [ ] **Step 4: Spec status**

In `docs/design/photogrammetry-ui-spec.md` change the Status line to `**Status:** implemented 2026-08-26 (plan docs/superpowers/plans/2026-08-26-photogrammetry-ui.md); worker spec pending`.

- [ ] **Step 5: Full verification**

```bash
cd chat-api && uv run pytest tests/unit -q
cd ../chat-vue && npm run type-check && npm run build
```
Expected: all green.

Migration round-trip (needs the compose Postgres running — `cd chat-api && docker compose up -d db`):
```bash
cd chat-api && uv run alembic -c app/db/alembic.ini upgrade head && uv run alembic -c app/db/alembic.ini downgrade -1 && uv run alembic -c app/db/alembic.ini upgrade head
```
Expected: three clean runs; `photogrammetry_jobs` present after the last.

Manual walkthrough (Neil, or whoever has a Cognito login for the local app):
1. `chat-api/.env`: `USE_MOCK_PHOTOGRAMMETRY=true`, `CORS_ORIGINS=["http://localhost:5173"]`; `docker compose up`.
2. `chat-vue`: `npm run dev`; sign in; click **Scan**.
3. **Sample** → a "Sample scan" appears, the stage strip walks four steps in ~10 s, then the placeholder torus renders with the amber "placeholder mesh" notice. Orbit it with the mouse.
4. **+ New scan** → drop the 22 files from `chat-api/app/assets/photogrammetry/images/` → *Uploading n/22* → same walk → viewer.
5. Drop 3 files → inline "Add at least 5 photos"; the button stays disabled.
6. ✕ on a card → confirm → gone; reload → list and any in-flight polling resume.
Record the outcome (and a screenshot) in the PR description.

- [ ] **Step 6: Commit**

```bash
git add docs/mock-api.md chat-vue/CLAUDE.md CLAUDE.md docs/design/photogrammetry-ui-spec.md
git commit -m "docs: photogrammetry mock mode, page layout and API surface"
```

---

## Self-review

**Spec coverage.** §1 contract → Tasks 1, 2, 5, 7 (all seven endpoints, state machine, key layout, `mock` flag). §2 backend → Tasks 1–7 (model, migration, schemas, repo, service, mock, deps, router, sink registration, settings, assets). §3 frontend → Tasks 8–11 (route, Scan tab in all three sidebars, api lib, store with 4-wide uploads and 3 s polling, view, every listed component, `isCustomElement`, types). §4 sample data/local dev → Tasks 4, 12. §5 testing → tests in every backend task; type-check + build gates on every frontend task; migration round-trip and manual walkthrough in Task 12. §6 out of scope — untouched.

**Deviations from the spec, all reflected in the amended spec:** `job_id` instead of `id`; cursor pagination `{items, next_cursor}` instead of `{jobs, total}`; the stage strip is its own `StageStrip.vue` rather than inside the badge; the real path's `confirm` checks upload completeness by listing the prefix (`image_count` keys present) rather than one `head_object` per key, because extensions are not stored; the photogrammetry router builds its own `GpuController` bound to the photogrammetry task family.

**Placeholder scan.** None — every step carries the code or the exact command.

**Type consistency.** `create_job(job_id, user_id, name, image_count, input_prefix)` is used by Tasks 2, 5, 6; `update_job_status(job_id, status, *, stage, mesh_s3_key, preview_s3_key, error_message)` in Tasks 2, 5, 6; `get_job_any` added in Task 6 and mocked in the Task 5 fixture as instructed; `generate_presigned_download_url(key, ttl_seconds)` / `write_object(key, bytes)` in Tasks 3, 5, 6; store API (`submitScan`, `submitSampleJob`, `fetchMeshUrl`, `uploadProgress`, `pollingActive`) matches its consumers in Tasks 9–11; `ScanStatusBadge`/`StageStrip`/`MeshViewer` props match their call sites.
