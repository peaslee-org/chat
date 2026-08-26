from fastapi import APIRouter

from app.api.v1.transcribe import jobs, speakers
from app.config import get_settings

router = APIRouter()
router.include_router(speakers.router)
router.include_router(jobs.router)

_settings = get_settings()
if _settings.use_mock_transcription or _settings.use_mock_photogrammetry:
    from app.api.v1.transcribe import dev
    router.include_router(dev.router)
