from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.gpu import deps as gpu_deps
from app.config import get_settings
from app.dependencies import get_db
from app.repositories.gpu import GpuSessionRepository
from app.repositories.photogrammetry import PhotogrammetryRepository
from app.services.audio_storage import AudioStorageService, LocalAudioStorageService
from app.services.ecs_launcher import EcsWorkerLauncher
from app.services.gpu_controller import GpuController
from app.services.photogrammetry_service import LocalPhotogrammetryService, PhotogrammetryService

# Launcher for the *photogrammetry* task family — separate from the transcription one in
# gpu/deps.py, same cluster and capacity provider, same gpu_sessions ledger and caps.
_launchers: dict[tuple, EcsWorkerLauncher] = {}


def _get_launcher(s) -> EcsWorkerLauncher:
    key = (s.gpu_cluster, s.gpu_photogrammetry_task_family, s.gpu_capacity_provider, s.aws_region)
    launcher = _launchers.get(key)
    if launcher is None:
        launcher = _launchers[key] = EcsWorkerLauncher(*key)
    return launcher


def get_photogrammetry_service(db: AsyncSession = Depends(get_db)) -> PhotogrammetryService:
    s = get_settings()
    repo = PhotogrammetryRepository(db)
    if s.use_mock_photogrammetry:
        storage = LocalAudioStorageService(s.mock_upload_base_url, s.local_storage_path)
        return LocalPhotogrammetryService(repo, storage, s)
    gpu = None
    if s.gpu_controller_enabled and s.gpu_photogrammetry_task_family:
        gpu = GpuController(
            GpuSessionRepository(db), _get_launcher(s), s,
            cost_client=gpu_deps._get_cost_client(s),
        )
    return PhotogrammetryService(repo, AudioStorageService(s), s, gpu)
