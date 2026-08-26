# ADR 004 — The transcription worker is a run-to-completion task on a shared GPU capacity provider

**Status:** Accepted 2026-08-25. Supersedes the "ECS service + hand-run start/stop script + worker-paused flag" operating model.

## Context
The worker needs a GPU (ADR 002) but runs rarely. As an ECS service on a hand-scaled ASG it was
either idle-and-billing or off-and-unreachable; jobs submitted while off died in SQS after 24 h; the
UI learned about it from an S3 flag someone had to remember to flip.

## Decision
- The GPU ASG is an **ECS capacity provider** (`gpu-<env>`, spot, min 0, managed scaling + managed
  termination protection), attached to the API's cluster and owned by the `prod` environment. It is
  tenant-agnostic; the worker is its first tenant.
- The worker is launched with **`RunTask`** by the API — on job confirm, on a "Warm it up" request,
  or when a status poll finds an active job and no worker — idempotently, under a Postgres advisory
  lock. It **exits itself** after `IDLE_EXIT_SECONDS` without work (deferred by a warm request), at
  `MAX_LIFETIME_SECONDS`, or on a spot notice (between messages). The capacity provider scales the
  instance in when the task ends.
- **Caps in three independent layers:** app (daily/monthly GPU-hours, per-user warms; admin
  bypass), worker (max lifetime), AWS (ASG `max_size`, cost-allocation tag, Budget, 4-hour alarm).
- `worker_state {off|starting|running}` is derived from `ListTasks`; the S3 flag is gone.

## Consequences
- A first job after idle waits for an instance (minutes; a pre-baked AMI keeps it short). The UI
  says so instead of spinning.
- Two tenants at once mean two instances (ECS pins a GPU to one task).
- Spend is visible in-app (`/gpu/usage`) and in Budgets; nothing can run longer than
  `max_size × MAX_LIFETIME_SECONDS` without a human.
