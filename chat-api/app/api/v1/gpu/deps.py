from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_db
from app.repositories.gpu import GpuSessionRepository
from app.services.cost_explorer import CostExplorerClient
from app.services.ecs_launcher import EcsWorkerLauncher, MockEcsWorkerLauncher
from app.services.gpu_controller import GpuController

_mock_launcher = MockEcsWorkerLauncher()   # one per process so state persists across requests


def is_admin(user: dict) -> bool:
    return "admin" in (user.get("cognito:groups") or [])


def get_gpu_controller(db: AsyncSession = Depends(get_db)) -> GpuController | None:
    s = get_settings()
    if s.use_mock_transcription:
        return GpuController(GpuSessionRepository(db), _mock_launcher, s)
    if not s.gpu_controller_enabled:
        return None
    launcher = EcsWorkerLauncher(s.gpu_cluster, s.gpu_worker_task_family, s.gpu_capacity_provider, s.aws_region)
    return GpuController(GpuSessionRepository(db), launcher, s, cost_client=CostExplorerClient(s.aws_region))
