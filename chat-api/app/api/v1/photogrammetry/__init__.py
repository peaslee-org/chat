from fastapi import APIRouter

from app.api.v1.photogrammetry import jobs

router = APIRouter()
router.include_router(jobs.router)
