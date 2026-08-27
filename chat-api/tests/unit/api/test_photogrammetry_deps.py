"""Service selection: mock vs real, and the real path's GPU controller only when deployed."""
from unittest.mock import MagicMock, patch

from app.api.v1.photogrammetry import deps
from app.services.photogrammetry_service import LocalPhotogrammetryService, PhotogrammetryService


def make_settings(**over):
    d = dict(use_mock_photogrammetry=False, mock_upload_base_url="http://localhost:8000",
             local_storage_path="/tmp/x", gpu_controller_enabled=True, use_mock_transcription=False,
             gpu_cluster="c", gpu_photogrammetry_task_family="photogrammetry-worker",
             gpu_capacity_provider="cp", aws_region="us-east-1")
    d.update(over)
    return MagicMock(**d)


def setup_function(_):
    deps.gpu_deps._launchers.clear()


def test_mock_flag_selects_local_service():
    settings = make_settings(use_mock_photogrammetry=True)
    with patch.object(deps, "get_settings", return_value=settings):
        svc = deps.get_photogrammetry_service(db=MagicMock())
    assert isinstance(svc, LocalPhotogrammetryService)
    assert svc._gpu is None


def test_real_service_without_task_family_has_no_gpu():
    settings = make_settings(gpu_photogrammetry_task_family="")
    with patch.object(deps, "get_settings", return_value=settings), \
         patch.object(deps, "AudioStorageService"):
        svc = deps.get_photogrammetry_service(db=MagicMock())
    assert type(svc) is PhotogrammetryService
    assert svc._gpu is None


def test_real_service_with_task_family_builds_cached_launcher():
    s = make_settings()
    with patch.object(deps, "get_settings", return_value=s), \
         patch.object(deps, "AudioStorageService"), \
         patch.object(deps.gpu_deps, "EcsWorkerLauncher") as launcher_cls, \
         patch.object(deps.gpu_deps, "_get_cost_client", return_value=MagicMock()):
        svc1 = deps.get_photogrammetry_service(db=MagicMock())
        svc2 = deps.get_photogrammetry_service(db=MagicMock())
    assert svc1._gpu is not None and svc2._gpu is not None
    assert svc1._gpu._family == "photogrammetry"
    launcher_cls.assert_called_once_with("c", "photogrammetry-worker", "cp", "us-east-1")
