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
    AudioUrlResponse,
    CompileSettings,
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
    svc.compile_transcript = AsyncMock(return_value=TranscriptResponse(segments=[]))
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
    svc.rerun_job = AsyncMock(return_value=JobStatusResponse(
        job_id=uuid4(),
        status="transcribing",
        speaker_count_hint=None,
        language="en-US",
        created_at=_now(),
        updated_at=_now(),
    ))
    svc.get_job_audio_url = AsyncMock(return_value=AudioUrlResponse(
        url="https://dl/audio/user1/job1/source",
        download_url="https://dl/audio/user1/job1/source?dl=job-audio",
        filename="job-audio",
        expires_at=_now(),
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


class TestRerunJob:
    async def test_rerun_returns_202_with_new_job(self, client):
        ac, svc = client
        job_id = uuid4()
        new_job_id = uuid4()
        svc.rerun_job.return_value = JobStatusResponse(
            job_id=new_job_id,
            status="transcribing",
            speaker_count_hint=None,
            language="en-US",
            created_at=_now(),
            updated_at=_now(),
        )
        response = await ac.post(
            f"/api/v1/transcribe/jobs/{job_id}/rerun",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 202
        assert response.json()["job_id"] == str(new_job_id)
        svc.rerun_job.assert_awaited_once_with("user1", job_id)

    async def test_rerun_404_when_source_not_found_or_not_owned(self, client):
        ac, svc = client
        svc.rerun_job.side_effect = NotFoundError("Job not found")
        response = await ac.post(
            f"/api/v1/transcribe/jobs/{uuid4()}/rerun",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 404

    async def test_rerun_404_when_audio_object_gone(self, client):
        ac, svc = client
        svc.rerun_job.side_effect = NotFoundError("Audio for this job is no longer available")
        response = await ac.post(
            f"/api/v1/transcribe/jobs/{uuid4()}/rerun",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 404
        assert "no longer available" in response.json()["detail"]

    async def test_rerun_409_when_no_audio_s3_key(self, client):
        ac, svc = client
        svc.rerun_job.side_effect = ConflictError("Job has no audio to rerun")
        response = await ac.post(
            f"/api/v1/transcribe/jobs/{uuid4()}/rerun",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 409


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


class TestSamples:
    async def test_samples_200(self, client):
        from app.schemas.transcription import (
            SampleAudioItem,
            SamplePreviewResponse,
            SampleSpeakerItem,
        )

        ac, svc = client
        svc.get_samples = AsyncMock(return_value=SamplePreviewResponse(
            name="Sample conversation",
            audio=SampleAudioItem(filename="conversation", url="https://dl/samples/conversation.wav"),
            speakers=[
                SampleSpeakerItem(speaker_name="Barry", url="https://dl/samples/speakers/barry.wav"),
                SampleSpeakerItem(speaker_name="Jane", url="https://dl/samples/speakers/jane.wav"),
            ],
        ))
        r = await ac.get(
            "/api/v1/transcribe/samples",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Sample conversation"
        assert body["audio"]["filename"] == "conversation"
        assert body["audio"]["url"] == "https://dl/samples/conversation.wav"
        assert body["speakers"][0] == {
            "speaker_name": "Barry", "url": "https://dl/samples/speakers/barry.wav"
        }
        assert body["speakers"][1] == {
            "speaker_name": "Jane", "url": "https://dl/samples/speakers/jane.wav"
        }

    async def test_samples_409_when_not_uploaded(self, client):
        ac, svc = client
        svc.get_samples = AsyncMock(side_effect=ConflictError("Sample audio has not been uploaded"))
        r = await ac.get(
            "/api/v1/transcribe/samples",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert r.status_code == 409


class TestJobAudioUrl:
    async def test_returns_200_with_urls(self, client):
        ac, svc = client
        job_id = uuid4()
        r = await ac.get(
            f"/api/v1/transcribe/jobs/{job_id}/audio",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["url"] == "https://dl/audio/user1/job1/source"
        assert body["download_url"] == "https://dl/audio/user1/job1/source?dl=job-audio"
        assert body["filename"] == "job-audio"
        assert "expires_at" in body
        svc.get_job_audio_url.assert_awaited_once_with("user1", job_id)

    async def test_404_when_job_not_found_or_not_owned(self, client):
        ac, svc = client
        svc.get_job_audio_url.side_effect = NotFoundError("Job not found")
        r = await ac.get(
            f"/api/v1/transcribe/jobs/{uuid4()}/audio",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert r.status_code == 404

    async def test_404_when_audio_object_gone(self, client):
        ac, svc = client
        svc.get_job_audio_url.side_effect = NotFoundError(
            "Input audio is no longer available — it may have expired from storage"
        )
        r = await ac.get(
            f"/api/v1/transcribe/jobs/{uuid4()}/audio",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert r.status_code == 404

    async def test_404_when_job_has_no_audio(self, client):
        ac, svc = client
        svc.get_job_audio_url.side_effect = NotFoundError("Job has no input audio")
        r = await ac.get(
            f"/api/v1/transcribe/jobs/{uuid4()}/audio",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert r.status_code == 404


class TestCompileTranscript:
    HEADERS = {"Authorization": "Bearer fake-token"}

    async def test_posts_settings_and_returns_transcript(self, client):
        ac, svc = client
        job_id = uuid4()
        body = {"cosine_dist_threshold": 0.3, "separation_min": 0.1, "quality_min": 0.0, "confidence_min": 0.0}
        res = await ac.post(f"/api/v1/transcribe/jobs/{job_id}/compile", json=body, headers=self.HEADERS)
        assert res.status_code == 200
        assert "turns" in res.json() and "settings" in res.json()
        _user, jid, settings = svc.compile_transcript.await_args.args
        assert jid == job_id and settings == CompileSettings(**body)

    async def test_422_on_out_of_range_settings(self, client):
        ac, _ = client
        res = await ac.post(
            f"/api/v1/transcribe/jobs/{uuid4()}/compile",
            json={"cosine_dist_threshold": 0, "separation_min": 0, "quality_min": 0, "confidence_min": 0},
            headers=self.HEADERS,
        )
        assert res.status_code == 422

    async def test_409_when_service_conflicts(self, client):
        ac, svc = client
        svc.compile_transcript.side_effect = ConflictError("no matching data")
        res = await ac.post(f"/api/v1/transcribe/jobs/{uuid4()}/compile", json={}, headers=self.HEADERS)
        assert res.status_code == 409
