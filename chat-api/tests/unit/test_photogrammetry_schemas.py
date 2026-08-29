from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.photogrammetry import (
    MIN_IMAGES,
    JobCreateRequest,
    JobStatusResponse,
    extension_of,
)


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


def test_status_response_warnings_default_to_empty_list():
    now = datetime.now(timezone.utc)
    r = JobStatusResponse(job_id=uuid4(), name="n", status="queued", image_count=5, created_at=now, updated_at=now)
    assert r.warnings == []


def test_photo_listing_schemas_shape():
    from app.schemas.photogrammetry import JobPhotosResponse, PhotoItem, SamplePhotosResponse

    item = PhotoItem(filename="0001.jpg", url="https://dl/0001.jpg", thumb_url="https://dl/t.jpg")
    assert JobPhotosResponse(photos=[item]).model_dump()["photos"][0]["thumb_url"] == "https://dl/t.jpg"
    sample = SamplePhotosResponse(name="Sample scan", image_count=1, photos=[item])
    assert sample.model_dump() == {
        "name": "Sample scan", "image_count": 1,
        "photos": [{"filename": "0001.jpg", "url": "https://dl/0001.jpg", "thumb_url": "https://dl/t.jpg"}],
    }
