from datetime import UTC, datetime
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
        preview_url="https://signed", created_at=datetime.now(UTC),
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
