# gpu-worker

Shared Python package (`gpu_worker`) for the lifecycle code both GPU workers need and neither
should own: the idle-aware SQS loop, the `gpu_sessions` ledger, spot and admin-release handling,
ECS/EC2 metadata. `transcription-worker/` and `photogrammetry-worker/` each vendor it at build
time — their Dockerfiles copy `gpu-worker/` from the repo-root build context and `pip install`
it — which is why a change here rebuilds **both** images (`deploy.yml` runs both worker workflows
on `gpu-worker/**`).

```bash
cd gpu-worker && uv sync --extra dev
uv run pytest -q          # 43 tests (2026-08-29); no AWS or DB
```

## Modules

| Module | Role |
|---|---|
| `loop.py` | `WorkerLoop` / `LoopConfig`: poll → handle → idle accounting. Exits on idle (`IDLE_EXIT_SECONDS`, extended by the ledger's `warm_until`), max lifetime, spot notice, or admin release; closes the session with the reason |
| `sqs.py` | `run_sqs_worker(handlers, …)`: long-poll, dispatch by message `type`, visibility-timeout extender thread, `Interrupted` on spot notice (message released with `VisibilityTimeout=0`), `receive_count(msg)` (`ApproximateReceiveCount`) for handlers' attempt gates |
| `session.py` | `GpuSessionStore`: best-effort writes to this task's `gpu_sessions` row (found by task ARN) — `claim()` on the first message (`started_processing_at`, `instance_id`, `instance_booted_at`), `heartbeat()`, `warm_until()` / `release_mode()` readers, `close(end_reason)`. DB errors are logged once, never raised |
| `db.py` | Sync SQLAlchemy session factory (asyncpg DSN normalised to psycopg2) and the worker-side `GpuSession` model |
| `host.py` | `boot_time(now)`: the EC2 instance's boot time from `/proc/uptime` (the container shares the host kernel); `None` when unreadable |
| `ecs_metadata.py` | Task ARN from the ECS metadata v4 endpoint; instance id from IMDSv2; `None` off ECS/EC2 |
| `spot_watcher.py` | Daemon thread polling the IMDS spot termination notice; sets the interrupt flag. No-op off EC2 |
| `release_watcher.py` | Daemon thread polling the ledger row's `release_mode` every 10 s: `graceful` → exit after the current job; `immediate` → abort the current job (honoured by the photogrammetry runner; the transcription job path does not check it yet, `docs/TODO.md`) |

The API side of the same ledger is `chat-api/app/services/gpu_controller.py` /
`repositories/gpu.py`: it creates the row at `RunTask`, records the promised startup estimate and
the ECS task timings, and reads `started_processing_at − started_at` and `instance_booted_at` to
measure cold vs warm startup times for the estimate shown to users.
