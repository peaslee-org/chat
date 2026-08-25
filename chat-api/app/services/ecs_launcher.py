"""Thin ECS wrapper: is a worker task alive, and start one. No policy here."""
import boto3


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
        arns = self._ecs.list_tasks(
            cluster=self._cluster, family=self._family, desiredStatus="RUNNING"
        ).get("taskArns", [])
        if not arns:
            return []
        tasks = self._ecs.describe_tasks(cluster=self._cluster, tasks=arns).get("tasks", [])
        return [t["lastStatus"] for t in tasks]

    def run_worker_task(self, started_by: str) -> str:
        resp = self._ecs.run_task(
            cluster=self._cluster,
            taskDefinition=self._family,          # latest ACTIVE revision
            count=1,
            capacityProviderStrategy=[{"capacityProvider": self._cp, "weight": 1}],
            startedBy=started_by[:36],
        )
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

    def run_worker_task(self, started_by: str) -> str:
        arn = f"arn:aws:ecs:local:000000000000:task/mock/{len(self.tasks) + 1}"
        self.tasks.append(arn)
        return arn
