from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.gpu.deps import get_gpu_controller
from app.dependencies import get_current_user
from app.main import app
from app.schemas.gpu import GpuStateResponse
from app.services.gpu_controller import GpuCapExceeded

H = {"Authorization": "Bearer fake-token"}


@pytest.fixture
async def client():
    ctl = MagicMock()
    ctl.get_state = AsyncMock(return_value=GpuStateResponse(worker_state="off", estimated_wait_seconds=180))
    ctl.ensure_worker = AsyncMock(return_value=GpuStateResponse(worker_state="starting", estimated_wait_seconds=120))
    app.dependency_overrides[get_gpu_controller] = lambda: ctl
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user1", "cognito:groups": []}
    with patch("app.db.session.init_db", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, ctl
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
    app.dependency_overrides[get_gpu_controller] = lambda: None
    r = await ac.post("/api/v1/gpu/warm", headers=H)
    assert r.status_code == 503
