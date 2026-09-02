"""Unit tests for transcribe speaker endpoints."""
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.api.v1.transcribe.deps import get_transcription_service
from app.dependencies import get_current_user
from app.core.exceptions import NotFoundError
from app.schemas.transcription import (
    AudioUrlResponse,
    SampleResponse,
    SampleUploadInitResponse,
    SpeakerListResponse,
    SpeakerResponse,
)


def make_mock_service():
    svc = AsyncMock()
    svc.create_speaker = AsyncMock(return_value=SpeakerResponse(
        speaker_id=uuid4(),
        speaker_name="Test Speaker",
        created_at=datetime.now(timezone.utc),
    ))
    svc.list_speakers = AsyncMock(return_value=SpeakerListResponse(items=[], next_cursor=None))
    svc.delete_speaker = AsyncMock(return_value=None)
    svc.initiate_sample_upload = AsyncMock(return_value=SampleUploadInitResponse(
        sample_id=uuid4(),
        upload_url="https://s3.example.com/upload",
    ))
    svc.confirm_sample_upload = AsyncMock(return_value=SampleResponse(
        sample_id=uuid4(),
        status="processing",
        duration_seconds=30.0,
        created_at=datetime.now(timezone.utc),
    ))
    svc.delete_sample = AsyncMock(return_value=None)
    svc.get_sample_audio_url = AsyncMock(return_value=AudioUrlResponse(
        url="https://dl/audio/user1/speakers/sp1/samples/sm1",
        download_url="https://dl/audio/user1/speakers/sp1/samples/sm1?dl=speaker-sample",
        filename="speaker-sample",
        expires_at=datetime.now(timezone.utc),
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


class TestCreateSpeaker:
    async def test_returns_202(self, client):
        ac, svc = client
        response = await ac.post(
            "/api/v1/transcribe/speakers",
            json={"speaker_name": "Alice"},
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 202

    async def test_ownership_enforced_on_delete(self, client):
        ac, svc = client
        svc.delete_speaker.side_effect = NotFoundError("Speaker not found")
        speaker_id = uuid4()
        response = await ac.delete(
            f"/api/v1/transcribe/speakers/{speaker_id}",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 404


class TestSpeakerEndpoints:
    async def test_list_speakers_returns_200(self, client):
        ac, svc = client
        response = await ac.get(
            "/api/v1/transcribe/speakers",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 200
        assert "items" in response.json()

    async def test_create_speaker_returns_202(self, client):
        ac, svc = client
        response = await ac.post(
            "/api/v1/transcribe/speakers",
            json={"speaker_name": "Bob"},
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 202

    async def test_initiate_sample_returns_202(self, client):
        ac, svc = client
        speaker_id = uuid4()
        response = await ac.post(
            f"/api/v1/transcribe/speakers/{speaker_id}/samples",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 202

    async def test_speaker_not_found_returns_404(self, client):
        ac, svc = client
        svc.initiate_sample_upload.side_effect = NotFoundError("Speaker not found")
        speaker_id = uuid4()
        response = await ac.post(
            f"/api/v1/transcribe/speakers/{speaker_id}/samples",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 404


class TestSampleAudioUrl:
    async def test_returns_200_with_urls(self, client):
        ac, svc = client
        speaker_id, sample_id = uuid4(), uuid4()
        response = await ac.get(
            f"/api/v1/transcribe/speakers/{speaker_id}/samples/{sample_id}/audio",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["url"] == "https://dl/audio/user1/speakers/sp1/samples/sm1"
        assert body["download_url"] == "https://dl/audio/user1/speakers/sp1/samples/sm1?dl=speaker-sample"
        assert body["filename"] == "speaker-sample"
        assert "expires_at" in body
        svc.get_sample_audio_url.assert_awaited_once_with("user1", speaker_id, sample_id)

    async def test_404_when_speaker_not_found_or_not_owned(self, client):
        ac, svc = client
        svc.get_sample_audio_url.side_effect = NotFoundError("Speaker not found")
        response = await ac.get(
            f"/api/v1/transcribe/speakers/{uuid4()}/samples/{uuid4()}/audio",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 404

    async def test_404_when_sample_not_found(self, client):
        ac, svc = client
        svc.get_sample_audio_url.side_effect = NotFoundError("Sample not found")
        response = await ac.get(
            f"/api/v1/transcribe/speakers/{uuid4()}/samples/{uuid4()}/audio",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 404

    async def test_404_when_audio_object_gone(self, client):
        ac, svc = client
        svc.get_sample_audio_url.side_effect = NotFoundError(
            "Sample audio is no longer available — it may have expired from storage"
        )
        response = await ac.get(
            f"/api/v1/transcribe/speakers/{uuid4()}/samples/{uuid4()}/audio",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 404
