from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.gpu.deps import get_gpu_controller_by_family
from app.dependencies import get_current_user, get_db
from app.main import app
from app.schemas.gpu import GpuStateResponse
from app.services.gpu_controller import GpuCapExceeded

H = {"Authorization": "Bearer fake-token"}


@pytest.fixture
async def client():
    ctl = MagicMock()
    ctl.get_state = AsyncMock(return_value=GpuStateResponse(worker_state="off", estimated_wait_seconds=180))
    ctl.ensure_worker = AsyncMock(return_value=GpuStateResponse(worker_state="starting", estimated_wait_seconds=120))
    app.dependency_overrides[get_gpu_controller_by_family] = lambda: ctl
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user1", "cognito:groups": []}
    with patch("app.db.session.init_db", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, ctl
    app.dependency_overrides.clear()


@pytest.fixture
async def client_by_family():
    ctls = {}

    def build(db, s, family):
        ctl = ctls.setdefault(family, MagicMock())
        ctl.get_state = AsyncMock(return_value=GpuStateResponse(worker_state="off", estimated_wait_seconds=180))
        ctl.ensure_worker = AsyncMock(return_value=GpuStateResponse(worker_state="starting", estimated_wait_seconds=120))
        return ctl

    app.dependency_overrides[get_current_user] = lambda: {"sub": "user1", "cognito:groups": []}
    app.dependency_overrides[get_db] = lambda: None
    with patch("app.api.v1.gpu.deps.build_controller", side_effect=build), patch("app.db.session.init_db", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, ctls
    app.dependency_overrides.clear()


async def test_state(client):
    ac, _ = client
    r = await ac.get("/api/v1/gpu/state", headers=H)
    assert r.status_code == 200 and r.json()["worker_state"] == "off"


async def test_warm_calls_ensure_worker_with_user(client):
    ac, ctl = client
    r = await ac.post("/api/v1/gpu/warm", headers=H)
    assert r.status_code == 200 and r.json()["worker_state"] == "starting"
    ctl.ensure_worker.assert_awaited_once_with("warm", "user1", is_admin=False)


async def test_warm_429_on_cap(client):
    ac, ctl = client
    ctl.ensure_worker.side_effect = GpuCapExceeded("Daily GPU budget used (3 h). Resets at midnight UTC.")
    r = await ac.post("/api/v1/gpu/warm", headers=H)
    assert r.status_code == 429 and "Daily GPU budget" in r.json()["detail"]


async def test_503_when_controller_disabled(client):
    ac, _ = client
    app.dependency_overrides[get_gpu_controller_by_family] = lambda: None
    r = await ac.post("/api/v1/gpu/warm", headers=H)
    assert r.status_code == 503


async def test_state_defaults_to_transcription(client_by_family):
    ac, ctls = client_by_family
    r = await ac.get("/api/v1/gpu/state", headers=H)
    assert r.status_code == 200 and set(ctls) == {"transcription"}


async def test_state_family_photogrammetry(client_by_family):
    ac, ctls = client_by_family
    r = await ac.get("/api/v1/gpu/state?family=photogrammetry", headers=H)
    assert r.status_code == 200 and set(ctls) == {"photogrammetry"}


async def test_warm_family_photogrammetry(client_by_family):
    ac, ctls = client_by_family
    r = await ac.post("/api/v1/gpu/warm?family=photogrammetry", headers=H)
    assert r.status_code == 200
    ctls["photogrammetry"].ensure_worker.assert_awaited_once_with("warm", "user1", is_admin=False)


async def test_unknown_family_is_422(client_by_family):
    ac, _ = client_by_family
    assert (await ac.get("/api/v1/gpu/state?family=nope", headers=H)).status_code == 422


# ── POST /gpu/release (admin-only) ─────────────────────────────────────────────────────────────

@pytest.fixture
async def admin_client():
    from app.services.gpu_controller import GpuNoWorker
    ctl = MagicMock()
    ctl.release = AsyncMock(return_value=GpuStateResponse(worker_state="running", estimated_wait_seconds=0))
    app.dependency_overrides[get_gpu_controller_by_family] = lambda: ctl
    app.dependency_overrides[get_current_user] = lambda: {"sub": "admin1", "cognito:groups": ["admin"]}
    with patch("app.db.session.init_db", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, ctl
    app.dependency_overrides.clear()


async def test_release_defaults_to_graceful_for_admin(admin_client):
    ac, ctl = admin_client
    r = await ac.post("/api/v1/gpu/release", headers=H)
    assert r.status_code == 200 and r.json()["worker_state"] == "running"
    ctl.release.assert_awaited_once_with("graceful", "admin1")


async def test_release_immediate_mode(admin_client):
    ac, ctl = admin_client
    r = await ac.post("/api/v1/gpu/release?mode=immediate", headers=H)
    assert r.status_code == 200
    ctl.release.assert_awaited_once_with("immediate", "admin1")


async def test_release_forbidden_for_non_admin(client):
    ac, ctl = client
    ctl.release = AsyncMock()
    r = await ac.post("/api/v1/gpu/release", headers=H)
    assert r.status_code == 403
    ctl.release.assert_not_awaited()


async def test_release_409_without_live_worker(admin_client):
    from app.services.gpu_controller import GpuNoWorker
    ac, ctl = admin_client
    ctl.release = AsyncMock(side_effect=GpuNoWorker("no live worker"))
    r = await ac.post("/api/v1/gpu/release", headers=H)
    assert r.status_code == 409


async def test_release_rejects_bad_mode(admin_client):
    ac, _ = admin_client
    r = await ac.post("/api/v1/gpu/release?mode=now", headers=H)
    assert r.status_code == 422
