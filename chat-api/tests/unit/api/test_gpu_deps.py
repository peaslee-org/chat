"""I4: EcsWorkerLauncher and CostExplorerClient are process-wide singletons, not built per request."""
from unittest.mock import MagicMock, patch

from app.api.v1.gpu import deps


def make_settings(**overrides):
    defaults = dict(gpu_cluster="chat-api-prod", gpu_worker_task_family="transcription-prod-worker",
                     gpu_photogrammetry_task_family="photogrammetry-prod-worker",
                     gpu_capacity_provider="gpu-prod", aws_region="us-east-1",
                     use_mock_transcription=False, gpu_controller_enabled=True)
    defaults.update(overrides)
    return MagicMock(**defaults)


def setup_function(_):
    deps._launchers.clear()
    deps._cost_clients.clear()


def test_get_launcher_is_cached_for_the_same_settings():
    s = make_settings()
    assert deps.launcher_for(s, "transcription") is deps.launcher_for(s, "transcription")
    assert len(deps._launchers) == 1


def test_get_launcher_rebuilds_on_a_different_key():
    s1 = make_settings()
    s2 = make_settings(gpu_cluster="chat-api-dev")
    assert deps.launcher_for(s1, "transcription") is not deps.launcher_for(s2, "transcription")
    assert len(deps._launchers) == 2


def test_get_cost_client_is_cached_per_region():
    s = make_settings()
    assert deps._get_cost_client(s) is deps._get_cost_client(s)
    assert len(deps._cost_clients) == 1


def test_build_controller_photogrammetry_uses_its_task_family():
    s = make_settings(gpu_photogrammetry_task_family="photogrammetry-prod-worker")
    with patch.object(deps, "EcsWorkerLauncher") as L, patch.object(deps, "_get_cost_client"):
        ctl = deps.build_controller(MagicMock(), s, "photogrammetry")
    assert ctl is not None and ctl._family == "photogrammetry"
    assert L.call_args.args[1] == "photogrammetry-prod-worker"


def test_build_controller_photogrammetry_none_when_family_empty():
    s = make_settings(gpu_photogrammetry_task_family="")
    assert deps.build_controller(MagicMock(), s, "photogrammetry") is None
