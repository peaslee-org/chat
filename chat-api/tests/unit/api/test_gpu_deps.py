"""I4: EcsWorkerLauncher and CostExplorerClient are process-wide singletons, not built per request."""
from unittest.mock import MagicMock

from app.api.v1.gpu import deps as gpu_deps


def make_settings(**overrides):
    defaults = dict(gpu_cluster="chat-api-prod", gpu_worker_task_family="transcription-prod-worker",
                     gpu_capacity_provider="gpu-prod", aws_region="us-east-1")
    defaults.update(overrides)
    return MagicMock(**defaults)


def setup_function(_):
    gpu_deps._launchers.clear()
    gpu_deps._cost_clients.clear()


def test_get_launcher_is_cached_for_the_same_settings():
    s = make_settings()
    assert gpu_deps._get_launcher(s) is gpu_deps._get_launcher(s)
    assert len(gpu_deps._launchers) == 1


def test_get_launcher_rebuilds_on_a_different_key():
    s1 = make_settings()
    s2 = make_settings(gpu_cluster="chat-api-dev")
    assert gpu_deps._get_launcher(s1) is not gpu_deps._get_launcher(s2)
    assert len(gpu_deps._launchers) == 2


def test_get_cost_client_is_cached_per_region():
    s = make_settings()
    assert gpu_deps._get_cost_client(s) is gpu_deps._get_cost_client(s)
    assert len(gpu_deps._cost_clients) == 1
