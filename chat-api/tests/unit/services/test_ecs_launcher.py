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


def test_run_worker_task_sets_propagate_tags_and_disables_exec():
    client = MagicMock()
    client.run_task.return_value = {"tasks": [{"taskArn": "arn:task/1"}]}
    launcher = make_launcher(client)
    launcher.run_worker_task("user1")
    kwargs = client.run_task.call_args.kwargs
    assert kwargs["propagateTags"] == "TASK_DEFINITION"
    assert kwargs["enableExecuteCommand"] is False


def test_task_timings_returns_pull_and_start_timestamps():
    from datetime import datetime, timezone
    t0 = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)
    client = MagicMock()
    client.describe_tasks.return_value = {"tasks": [{
        "taskArn": "arn:task/1", "pullStartedAt": t0, "pullStoppedAt": t0.replace(minute=1), "startedAt": t0.replace(minute=2),
    }]}
    launcher = make_launcher(client)
    timings = launcher.task_timings("arn:task/1")
    assert timings == {"pull_started_at": t0, "pull_stopped_at": t0.replace(minute=1),
                       "container_started_at": t0.replace(minute=2)}
    client.describe_tasks.assert_called_once_with(cluster="cluster", tasks=["arn:task/1"])


def test_task_timings_missing_keys_are_none_and_unknown_task_is_none():
    client = MagicMock()
    client.describe_tasks.return_value = {"tasks": [{"taskArn": "arn:task/1"}]}
    assert make_launcher(client).task_timings("arn:task/1") == {
        "pull_started_at": None, "pull_stopped_at": None, "container_started_at": None}
    client.describe_tasks.return_value = {"tasks": [], "failures": [{"reason": "MISSING"}]}
    assert make_launcher(client).task_timings("arn:task/1") is None


def test_task_timings_wraps_client_error():
    client = MagicMock()
    client.describe_tasks.side_effect = ClientError({"Error": {"Code": "Boom", "Message": "x"}}, "DescribeTasks")
    with pytest.raises(GpuLaunchError):
        make_launcher(client).task_timings("arn:task/1")


def test_mock_launcher_task_timings_are_plausible():
    from app.services.ecs_launcher import MockEcsWorkerLauncher
    m = MockEcsWorkerLauncher()
    arn = m.run_worker_task("u")
    t = m.task_timings(arn)
    assert t["pull_started_at"] <= t["pull_stopped_at"] <= t["container_started_at"]
    assert m.task_timings("arn:nope") is None
