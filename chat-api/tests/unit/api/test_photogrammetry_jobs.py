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
        job_id=uuid4(),
        uploads=[
            UploadTarget(filename=f, key=f"k/{i:04d}.jpg", url="https://up")
            for i, f in enumerate(FILES, 1)
        ],
    ))
    svc.confirm_job = AsyncMock(return_value=None)
    svc.list_jobs = AsyncMock(
        return_value=JobListResponse(items=[status_response()], next_cursor=None)
    )
    svc.get_job_status = AsyncMock(return_value=status_response(status="processing", stage="dense"))
    svc.delete_job = AsyncMock(return_value=None)
    svc.get_mesh_url = AsyncMock(
        return_value=MeshUrlResponse(
            url="https://dl/mesh.glb", expires_at=datetime.now(timezone.utc)
        )
    )
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
        body = {"name": "Mug", "filenames": FILES}
        r = await ac.post("/api/v1/photogrammetry/jobs", json=body, headers=H)
        assert r.status_code == 202
        assert len(r.json()["uploads"]) == 6
        assert svc.create_job.await_args.args[0] == "user1"

    async def test_422_too_few_files(self, client):
        ac, _ = client
        r = await ac.post("/api/v1/photogrammetry/jobs", json={"filenames": FILES[:4]}, headers=H)
        assert r.status_code == 422

    async def test_422_bad_extension(self, client):
        ac, _ = client
        body = {"filenames": FILES[:5] + ["x.gif"]}
        r = await ac.post("/api/v1/photogrammetry/jobs", json=body, headers=H)
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
