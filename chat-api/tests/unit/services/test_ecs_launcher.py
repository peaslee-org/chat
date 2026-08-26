from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from app.services.ecs_launcher import EcsWorkerLauncher, GpuLaunchError


def make_launcher(client):
    with patch("boto3.client", return_value=client):
        return EcsWorkerLauncher("cluster", "family", "cp", "us-east-1")


def test_run_worker_task_wraps_client_error():
    client = MagicMock()
    client.run_task.side_effect = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}, "RunTask"
    )
    launcher = make_launcher(client)
    with pytest.raises(GpuLaunchError):
        launcher.run_worker_task("user1")


def test_run_worker_task_wraps_boto_core_error():
    client = MagicMock()
    client.run_task.side_effect = BotoCoreError()
    launcher = make_launcher(client)
    with pytest.raises(GpuLaunchError):
        launcher.run_worker_task("user1")


def test_list_worker_tasks_wraps_client_error():
    client = MagicMock()
    client.list_tasks.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "ListTasks"
    )
    launcher = make_launcher(client)
    with pytest.raises(GpuLaunchError):
        launcher.list_worker_tasks()
