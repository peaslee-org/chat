"""Photogrammetry jobs: upload a photo set, queue it for the GPU worker, serve the result.

`PhotogrammetryService` is the real path (S3 + ECS via the shared GpuController).
`LocalPhotogrammetryService` (Task 6) is the in-process mock selected by USE_MOCK_PHOTOGRAMMETRY.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
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

logger = logging.getLogger(__name__)

DOWNLOAD_TTL_SECONDS = 900
ACTIVE_FOR_GPU = ("queued", "processing")


def default_job_name(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"Scan {now:%Y-%m-%d %H:%M}"


class PhotogrammetryService:
    is_mock = False

    def __init__(self, repo: PhotogrammetryRepository, storage, settings, gpu=None, sqs=None):
        self._repo = repo
        self._storage = storage
        self._settings = settings
        self._gpu = gpu
        self._sqs = sqs

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
        if self._sqs is not None:
            self._sqs.publish_photogrammetry_job(job_id)  # after the commit so the worker finds the row
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
        return JobListResponse(
            items=[self._to_response(j) for j in items], next_cursor=next_cursor
        )

    async def get_mesh_url(self, user_id: str, job_id: UUID) -> MeshUrlResponse:
        job = await self._get_or_404(user_id, job_id)
        if job.status != "complete" or not job.mesh_s3_key:
            raise ConflictError("Mesh not yet available")
        return MeshUrlResponse(
            url=self._storage.generate_presigned_download_url(
                job.mesh_s3_key, ttl_seconds=DOWNLOAD_TTL_SECONDS
            ),
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
            self._storage.generate_presigned_download_url(
                job.preview_s3_key, ttl_seconds=DOWNLOAD_TTL_SECONDS
            )
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


ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "photogrammetry"


class LocalPhotogrammetryService(PhotogrammetryService):
    """Mock for local dev (USE_MOCK_PHOTOGRAMMETRY=true): real Postgres, no S3, no ECS.

    confirm_job trusts the dev-upload sink and walks the job
    queued → processing(sfm → dense → mesh → texture) → complete on timers, then copies the
    committed placeholder mesh/preview into the sink under the job's output keys.
    """
    is_mock = True

    def __init__(self, repo: PhotogrammetryRepository, storage, settings):
        super().__init__(repo, storage, settings, gpu=None, sqs=None)

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
        try:
            await self._run_mock_process_job(job_id)
        except Exception:
            logger.exception("mock photogrammetry walk failed for job %s", job_id)

    async def _run_mock_process_job(self, job_id: UUID) -> None:
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
        if job is None:
            logger.info("mock photogrammetry walk: job %s deleted mid-walk, aborting", job_id)
            return
        output_prefix = job.input_prefix.rsplit("input/", 1)[0] + "output/"
        mesh_key = f"{output_prefix}mesh.glb"
        preview_key = f"{output_prefix}preview.png"
        self._storage.write_object(mesh_key, (ASSET_DIR / "mesh.glb").read_bytes())
        self._storage.write_object(preview_key, (ASSET_DIR / "preview.png").read_bytes())
        await set_status("complete", mesh_s3_key=mesh_key, preview_s3_key=preview_key)
