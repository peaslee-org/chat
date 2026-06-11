from fastapi import APIRouter

from app.api.v1.transcribe import jobs, speakers
from app.config import get_settings

router = APIRouter()
router.include_router(speakers.router)
router.include_router(jobs.router)

if get_settings().use_mock_transcription:
    from app.api.v1.transcribe import dev
    router.include_router(dev.router)
