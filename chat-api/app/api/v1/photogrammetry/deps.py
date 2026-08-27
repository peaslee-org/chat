from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.gpu import deps as gpu_deps
from app.config import get_settings
from app.dependencies import get_db
from app.repositories.photogrammetry import PhotogrammetryRepository
from app.services.audio_storage import AudioStorageService, LocalAudioStorageService
from app.services.photogrammetry_service import LocalPhotogrammetryService, PhotogrammetryService


def get_photogrammetry_service(db: AsyncSession = Depends(get_db)) -> PhotogrammetryService:
    s = get_settings()
    repo = PhotogrammetryRepository(db)
    if s.use_mock_photogrammetry:
        storage = LocalAudioStorageService(s.mock_upload_base_url, s.local_storage_path)
        return LocalPhotogrammetryService(repo, storage, s)
    gpu = gpu_deps.build_controller(db, s, "photogrammetry")
    return PhotogrammetryService(repo, AudioStorageService(s), s, gpu)
