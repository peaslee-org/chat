from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

MIN_IMAGES = 5
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}


def extension_of(filename: str) -> str:
    """Lower-cased extension without the dot; '' when there is none."""
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


class JobCreateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    filenames: List[str] = Field(..., min_length=MIN_IMAGES)

    @field_validator("filenames")
    @classmethod
    def _supported_images(cls, filenames: List[str]) -> List[str]:
        bad = [f for f in filenames if extension_of(f) not in ALLOWED_EXTENSIONS]
        if bad:
            raise ValueError(f"unsupported image type: {', '.join(bad[:3])}")
        return filenames


class UploadTarget(BaseModel):
    filename: str
    key: str
    url: str


class JobCreateResponse(BaseModel):
    job_id: UUID
    uploads: List[UploadTarget]


class JobStatusResponse(BaseModel):
    job_id: UUID
    name: str
    status: str
    stage: Optional[str] = None
    image_count: int
    preview_url: Optional[str] = None
    error_message: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    mock: bool = False
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    worker_state: Optional[str] = None
    estimated_wait_seconds: Optional[int] = None
    gpu_notice: Optional[str] = None


class JobListResponse(BaseModel):
    items: List[JobStatusResponse]
    next_cursor: Optional[str] = None


class SampleJobResponse(BaseModel):
    job_id: UUID


class MeshUrlResponse(BaseModel):
    url: str                                    # plain GET — what <model-viewer> loads
    download_url: str                           # same object, Content-Disposition: attachment
    preview_download_url: Optional[str] = None  # preview.png as an attachment, when it exists
    expires_at: datetime
