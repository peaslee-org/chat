from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_db
from app.repositories.gpu import GpuSessionRepository
from app.services.cost_explorer import CostExplorerClient
from app.services.ecs_launcher import EcsWorkerLauncher, MockEcsWorkerLauncher
from app.services.gpu_controller import GpuController

_mock_launcher = MockEcsWorkerLauncher()   # one per process so state persists across requests

# boto3 clients are lazy singletons keyed by the settings values they were built from — cheap to
# build once, wasteful to build per request; the key covers a settings change (e.g. in tests).
_launchers: dict[tuple, EcsWorkerLauncher] = {}
_cost_clients: dict[str, CostExplorerClient] = {}


def is_admin(user: dict) -> bool:
    return "admin" in (user.get("cognito:groups") or [])


def _get_launcher(s) -> EcsWorkerLauncher:
    key = (s.gpu_cluster, s.gpu_worker_task_family, s.gpu_capacity_provider, s.aws_region)
    launcher = _launchers.get(key)
    if launcher is None:
        launcher = _launchers[key] = EcsWorkerLauncher(*key)
    return launcher


def _get_cost_client(s) -> CostExplorerClient:
    client = _cost_clients.get(s.aws_region)
    if client is None:
        client = _cost_clients[s.aws_region] = CostExplorerClient(s.aws_region)
    return client


def get_gpu_controller(db: AsyncSession = Depends(get_db)) -> GpuController | None:
    s = get_settings()
    if s.use_mock_transcription:
        return GpuController(GpuSessionRepository(db), _mock_launcher, s)
    if not s.gpu_controller_enabled:
        return None
    return GpuController(GpuSessionRepository(db), _get_launcher(s), s, cost_client=_get_cost_client(s))
