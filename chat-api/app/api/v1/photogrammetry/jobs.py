from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.photogrammetry.deps import get_photogrammetry_service
from app.dependencies import get_current_user
from app.schemas.photogrammetry import (
    JobCreateRequest,
    JobCreateResponse,
    JobListResponse,
    JobStatusResponse,
    MeshUrlResponse,
    SampleJobResponse,
)
from app.services.photogrammetry_service import PhotogrammetryService

router = APIRouter()


@router.post("/jobs/sample", status_code=202, response_model=SampleJobResponse)
async def create_sample_job(
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> SampleJobResponse:
    return await service.create_sample_job(current_user["sub"])


@router.post("/jobs", status_code=202, response_model=JobCreateResponse)
async def create_job(
    body: JobCreateRequest,
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> JobCreateResponse:
    return await service.create_job(current_user["sub"], body)


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    cursor: Optional[str] = None,
    limit: int = Query(default=20, le=100),
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> JobListResponse:
    return await service.list_jobs(current_user["sub"], cursor, limit)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> JobStatusResponse:
    return await service.get_job_status(current_user["sub"], job_id)


@router.post("/jobs/{job_id}/confirm", status_code=202)
async def confirm_job(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> None:
    await service.confirm_job(current_user["sub"], job_id)


@router.get("/jobs/{job_id}/mesh", response_model=MeshUrlResponse)
async def get_mesh_url(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> MeshUrlResponse:
    return await service.get_mesh_url(current_user["sub"], job_id)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    service: PhotogrammetryService = Depends(get_photogrammetry_service),
) -> None:
    await service.delete_job(current_user["sub"], job_id)
