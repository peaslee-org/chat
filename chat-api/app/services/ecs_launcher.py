"""Thin ECS wrapper: is a worker task alive, and start one. No policy here."""
from datetime import datetime, timedelta, timezone
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError


class GpuLaunchError(Exception):
    pass


class EcsWorkerLauncher:
    def __init__(self, cluster: str, task_family: str, capacity_provider: str, region: str):
        self._cluster = cluster
        self._family = task_family
        self._cp = capacity_provider
        self._ecs = boto3.client("ecs", region_name=region)

    def list_worker_tasks(self) -> list[str]:
        # desiredStatus=RUNNING covers PROVISIONING/PENDING/ACTIVATING/RUNNING tasks.
        try:
            arns = self._ecs.list_tasks(
                cluster=self._cluster, family=self._family, desiredStatus="RUNNING"
            ).get("taskArns", [])
            if not arns:
                return []
            tasks = self._ecs.describe_tasks(cluster=self._cluster, tasks=arns).get("tasks", [])
        except (ClientError, BotoCoreError) as e:
            raise GpuLaunchError(str(e)) from e
        return [t["lastStatus"] for t in tasks]

    def task_timings(self, task_arn: str) -> Optional[dict]:
        """The task's image-pull window and container start (ECS-stamped, tz-aware), for the
        startup stage breakdown. None when ECS no longer knows the task."""
        try:
            tasks = self._ecs.describe_tasks(cluster=self._cluster, tasks=[task_arn]).get("tasks", [])
        except (ClientError, BotoCoreError) as e:
            raise GpuLaunchError(str(e)) from e
        if not tasks:
            return None
        t = tasks[0]
        return {
            "pull_started_at": t.get("pullStartedAt"),
            "pull_stopped_at": t.get("pullStoppedAt"),
            "container_started_at": t.get("startedAt"),
        }

    def run_worker_task(self, started_by: str) -> str:
        try:
            resp = self._ecs.run_task(
                cluster=self._cluster,
                taskDefinition=self._family,          # latest ACTIVE revision
                count=1,
                capacityProviderStrategy=[{"capacityProvider": self._cp, "weight": 1}],
                startedBy=started_by[:36],
                propagateTags="TASK_DEFINITION",
                enableExecuteCommand=False,
            )
        except (ClientError, BotoCoreError) as e:
            raise GpuLaunchError(str(e)) from e
        if resp.get("failures"):
            f = resp["failures"][0]
            raise GpuLaunchError(f"{f.get('reason')}: {f.get('detail')}")
        return resp["tasks"][0]["taskArn"]


class MockEcsWorkerLauncher:
    """Local dev: pretends a task starts immediately and stays running."""

    def __init__(self):
        self.tasks: list[str] = []

    def list_worker_tasks(self) -> list[str]:
        return ["RUNNING" for _ in self.tasks]

    def task_timings(self, task_arn: str) -> Optional[dict]:
        if task_arn not in self.tasks:
            return None
        now = datetime.now(timezone.utc)
        return {
            "pull_started_at": now - timedelta(seconds=40),
            "pull_stopped_at": now - timedelta(seconds=10),
            "container_started_at": now - timedelta(seconds=5),
        }

    def run_worker_task(self, started_by: str) -> str:
        arn = f"arn:aws:ecs:local:000000000000:task/mock/{len(self.tasks) + 1}"
        self.tasks.append(arn)
        return arn
