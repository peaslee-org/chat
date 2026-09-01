"""Unit tests for transcribe job endpoints."""
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.api.v1.transcribe.deps import get_transcription_service
from app.dependencies import get_current_user
from app.core.exceptions import (
    ConflictError,
    ConcurrentJobLimitExceeded,
    NotFoundError,
)
from app.schemas.transcription import (
    JobCreateResponse,
    JobListResponse,
    JobStatusResponse,
    TranscriptResponse,
)


def _now():
    return datetime.now(timezone.utc)


def make_mock_service():
    svc = AsyncMock()
    svc.initiate_job_upload = AsyncMock(return_value=JobCreateResponse(
        job_id=uuid4(),
        upload_url="https://s3.example.com/upload",
    ))
    svc.list_jobs = AsyncMock(return_value=JobListResponse(items=[], next_cursor=None))
    svc.get_job_status = AsyncMock(return_value=JobStatusResponse(
        job_id=uuid4(),
        status="pending",
        speaker_count_hint=None,
        language="en-US",
        created_at=_now(),
        updated_at=_now(),
    ))
    svc.confirm_job_upload = AsyncMock(return_value=None)
    svc.get_transcript = AsyncMock(return_value=TranscriptResponse(segments=[]))
    svc.delete_job = AsyncMock(return_value=None)
    svc.set_visibility = AsyncMock(return_value=JobStatusResponse(
        job_id=uuid4(),
        status="pending",
        speaker_count_hint=None,
        language="en-US",
        created_at=_now(),
        updated_at=_now(),
        is_public=True,
    ))
    return svc


@pytest.fixture
async def client():
    mock_service = make_mock_service()
    app.dependency_overrides[get_transcription_service] = lambda: mock_service
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user1"}
    with patch("app.db.session.init_db", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, mock_service
    app.dependency_overrides.clear()


class TestJobEndpoints:
    async def test_create_job_returns_202(self, client):
        ac, svc = client
        response = await ac.post(
            "/api/v1/transcribe/jobs",
            json={"speaker_count_hint": 2, "language": "en-US"},
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 202
        assert "upload_url" in response.json()

    async def test_create_job_429_when_limit_exceeded(self, client):
        ac, svc = client
        svc.initiate_job_upload.side_effect = ConcurrentJobLimitExceeded()
        response = await ac.post(
            "/api/v1/transcribe/jobs",
            json={"speaker_count_hint": 2, "language": "en-US"},
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 429

    async def test_list_jobs_returns_200(self, client):
        ac, svc = client
        response = await ac.get(
            "/api/v1/transcribe/jobs",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 200
        assert "items" in response.json()

    async def test_get_job_status_returns_200(self, client):
        ac, svc = client
        job_id = uuid4()
        response = await ac.get(
            f"/api/v1/transcribe/jobs/{job_id}",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 200

    async def test_get_job_status_404_not_found(self, client):
        ac, svc = client
        svc.get_job_status.side_effect = NotFoundError("Job not found")
        job_id = uuid4()
        response = await ac.get(
            f"/api/v1/transcribe/jobs/{job_id}",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 404

    async def test_get_transcript_409_when_not_ready(self, client):
        ac, svc = client
        svc.get_transcript.side_effect = ConflictError("Transcript not yet available")
        job_id = uuid4()
        response = await ac.get(
            f"/api/v1/transcribe/jobs/{job_id}/transcript",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 409

    async def test_get_transcript_200_when_complete(self, client):
        ac, svc = client
        job_id = uuid4()
        response = await ac.get(
            f"/api/v1/transcribe/jobs/{job_id}/transcript",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 200
        assert "segments" in response.json()

    async def test_delete_job_returns_204(self, client):
        ac, svc = client
        job_id = uuid4()
        response = await ac.delete(
            f"/api/v1/transcribe/jobs/{job_id}",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 204

    async def test_partial_transcript_flag_in_status(self, client):
        ac, svc = client
        job_id = uuid4()
        svc.get_job_status.return_value = JobStatusResponse(
            job_id=job_id,
            status="failed",
            speaker_count_hint=None,
            language="en-US",
            partial_transcript_available=True,
            created_at=_now(),
            updated_at=_now(),
        )
        response = await ac.get(
            f"/api/v1/transcribe/jobs/{job_id}",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 200
        assert response.json()["partial_transcript_available"] is True


class TestVisibility:
    async def test_patch_visibility(self, client):
        ac, svc = client
        jid = uuid4()
        r = await ac.patch(
            f"/api/v1/transcribe/jobs/{jid}",
            json={"is_public": True},
            headers={"Authorization": "Bearer fake-token"},
        )
        assert r.status_code == 200 and r.json()["is_public"] is True
        svc.set_visibility.assert_awaited_once_with("user1", jid, True)

    async def test_patch_visibility_not_owner_is_404(self, client):
        ac, svc = client
        svc.set_visibility.side_effect = NotFoundError("Job x not found")
        r = await ac.patch(
            f"/api/v1/transcribe/jobs/{uuid4()}",
            json={"is_public": True},
            headers={"Authorization": "Bearer fake-token"},
        )
        assert r.status_code == 404
