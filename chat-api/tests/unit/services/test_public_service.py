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
    m = MagicMock()
    m.configure_mock(**d)
    return m


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
    transcriptions.get_segment_stats_bulk.return_value = {tjob.id: (123.4, 56)}
    conversations.list_public.return_value = [
        MagicMock(id=uuid4(), title="t", model_id="m", created_at=datetime.now(timezone.utc))
    ]
    out = await svc.showcase()
    assert len(out.scans) == len(out.transcriptions) == len(out.conversations) == 1
    assert out.transcriptions[0].duration_seconds == 123.4
    transcriptions.get_segment_stats_bulk.assert_called_once_with([tjob.id])


async def test_showcase_missing_stats_default_to_none_and_zero():
    svc, scans, transcriptions, conversations, _ = make_service()
    scans.list_public_jobs.return_value = []
    tjob = MagicMock(id=uuid4(), created_at=datetime.now(timezone.utc), matched_speaker_count=None)
    transcriptions.list_public_jobs.return_value = [tjob]
    transcriptions.get_segment_stats_bulk.return_value = {}
    conversations.list_public.return_value = []
    out = await svc.showcase()
    assert out.transcriptions[0].duration_seconds is None
    assert out.transcriptions[0].segment_count is None
