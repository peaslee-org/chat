# Photogrammetry Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the GPU worker that turns a confirmed photogrammetry job's photos into `mesh.glb` + `preview.png`, and make the API's GPU controller and ledger safe for two task families on one pool.

**Architecture:** A new shared package `gpu-worker/` holds the lifecycle code (SQS loop, idle/max-lifetime exit, spot-interruption release, `gpu_sessions` ledger) that today lives inside `transcription-worker/`; both workers install it. `photogrammetry-worker/` is a thin SQS consumer whose handler drives COLMAP → OpenMVS → trimesh through stage-tracked subprocess calls. `chat-api` gains `gpu_sessions.family`, a family-scoped repository/controller, a publisher call on confirm, and `?family=` on the GPU status endpoints. Terraform adds `modules/photogrammetry` (queue, ECR, task family, roles, alarm) and the bucket lifecycle rule.

**Tech Stack:** Python 3.12, boto3, SQLAlchemy 2, pydantic-settings, pytest; COLMAP (`colmap/colmap:20260729.7651`), OpenMVS `v2.4.0`, trimesh, Pillow; FastAPI + Alembic (chat-api); Vue 3 + Pinia + TypeScript (chat-vue); Terraform (AWS provider), GitHub Actions OIDC.

**Spec:** `docs/design/photogrammetry-worker-spec.md` (implements the contract in `docs/design/photogrammetry-ui-spec.md` §1 and its §7 constraints).

## Global Constraints

- Python `>=3.12` everywhere; workers run tests with `uv run pytest -q` from their own directory; chat-api with `uv run pytest tests/unit -q` (must stay green — 144 tests today).
- Stage names written to `photogrammetry_jobs.stage` are exactly `sfm`, `dense`, `mesh`, `texture`. Statuses: `pending | queued | processing | complete | failed`.
- Output keys are **always** `photogrammetry/<user_id>/<job_id>/output/mesh.glb` and `…/output/preview.png`, derived from the job row's `user_id`, never from `input_prefix`.
- `gpu_sessions.family` values are the logical names `transcription` | `photogrammetry`; migration default `transcription`.
- Registration threshold: fail SfM when registered images `< ceil(0.6 × image_count)`. `RefineMesh` is skipped when `image_count > 100`. Job deadline `PHOTOGRAMMETRY_JOB_TIMEOUT_SECONDS` default `3600`; message text `Reconstruction exceeded 60 minutes`.
- Deterministic failures are **acked** (row `failed`); a spot interruption resets the row to `queued` and is **not** acked; any other crash is not acked (SQS redelivers, `maxReceiveCount` 3).
- Both worker Docker builds use the **repository root** as build context: `docker build -f <worker>/Dockerfile .`.
- Pinned images: `colmap/colmap:20260729.7651`; OpenMVS tag `v2.4.0`.
- Nothing in this plan applies Terraform or deploys; every task ends at a green test/validate and a commit on branch `photogrammetry-worker`.
- Commit messages use the repo's conventional prefixes (`feat(worker):`, `feat(api):`, `feat(vue):`, `infra:`, `refactor:`, `docs:`).

---

## File structure

**Create**
- `gpu-worker/pyproject.toml`, `gpu-worker/gpu_worker/{__init__,loop,spot_watcher,ecs_metadata,db,session,sqs}.py`, `gpu-worker/tests/{__init__,test_loop,test_spot_watcher,test_session,test_sqs}.py`
- `photogrammetry-worker/{pyproject.toml,Dockerfile,CLAUDE.md,main.py,config.py,models.py}`, `photogrammetry-worker/services/{__init__,s3.py}`, `photogrammetry-worker/pipeline/{__init__,runner,colmap,openmvs,export,reconstruct}.py`, `photogrammetry-worker/handlers/{__init__,photogrammetry}.py`, `photogrammetry-worker/tests/*`
- `.github/workflows/photogrammetry-worker.yml`
- `chat-api/app/db/migrations/versions/m3n4o5p6q7r8_add_gpu_sessions_family.py`
- `infra/modules/photogrammetry/{main,variables,outputs}.tf`

**Modify**
- `transcription-worker/{main.py,models.py,Dockerfile,pyproject.toml,CLAUDE.md}`; delete `worker_loop.py`, `services/{gpu_session,spot_watcher,ecs_metadata}.py`, `tests/{test_worker_loop,test_spot_watcher,test_gpu_session}.py`
- `.github/workflows/worker.yml`
- `chat-api/app/{models/gpu.py,schemas/gpu.py,config.py,repositories/gpu.py,services/gpu_controller.py,services/sqs_publisher.py,services/photogrammetry_service.py,api/v1/gpu/deps.py,api/v1/gpu/router.py (the file holding the routes),api/v1/photogrammetry/deps.py,.env.example}` + their tests
- `chat-vue/src/{lib/gpuApi.ts,stores/gpu.ts,components/transcribe/GpuStatusBar.vue,views/PhotogrammetryView.vue,types/index.ts (GpuUsage session type)}`
- `infra/modules/transcription/main.tf` (lifecycle rule), `infra/environments/transcription-prod/{main,variables}.tf`, `infra/environments/prod/main.tf`
- `scripts/deploy/build-gpu-ami.sh`, `docs/TODO.md`

---

# Part A — shared package `gpu-worker/`

### Task 1: Create `gpu-worker/` and move the lifecycle modules

**Files:**
- Create: `gpu-worker/pyproject.toml`, `gpu-worker/gpu_worker/__init__.py`, `gpu-worker/gpu_worker/loop.py`, `gpu-worker/gpu_worker/spot_watcher.py`, `gpu-worker/gpu_worker/ecs_metadata.py`, `gpu-worker/gpu_worker/db.py`, `gpu-worker/gpu_worker/session.py`, `gpu-worker/tests/__init__.py`, `gpu-worker/tests/test_loop.py`, `gpu-worker/tests/test_spot_watcher.py`, `gpu-worker/tests/test_session.py`
- Source (copied in this task, deleted in Task 3): `transcription-worker/worker_loop.py`, `transcription-worker/services/{spot_watcher,ecs_metadata,gpu_session}.py`, `transcription-worker/tests/{test_worker_loop,test_spot_watcher,test_gpu_session}.py`

**Interfaces:**
- Produces: `gpu_worker.loop.WorkerLoop(receive, process, sessions, interrupted, config: LoopConfig, clock=..., wall=...)` and `LoopConfig(idle_exit_seconds: int, max_lifetime_seconds: int)` — unchanged from `worker_loop.py`.
- Produces: `gpu_worker.spot_watcher.SpotWatcher` (class attr `interrupted: threading.Event`; `SpotWatcher(queue_url, receipt_handle, region)`, `SpotWatcher.idle_watcher(region)`, `.start()`, `.stop()`) — unchanged.
- Produces: `gpu_worker.ecs_metadata.task_arn() -> str | None`, `instance_id() -> str | None` — unchanged.
- Produces: `gpu_worker.db.make_session_factory(database_url: str) -> Callable[[], ContextManager[Session]]` and `gpu_worker.db.GpuSession` (own `Base`).
- Produces: `gpu_worker.session.GpuSessionStore(task_arn, instance_id, session_factory)` — `session_factory` **required**; methods `claim()`, `heartbeat()`, `warm_until()`, `close(end_reason)` unchanged.

- [ ] **Step 1: Package skeleton**

`gpu-worker/pyproject.toml`:

```toml
[project]
name = "gpu-worker"
version = "0.1.0"
description = "Lifecycle code shared by the GPU workers: SQS loop, idle exit, spot release, gpu_sessions ledger"
requires-python = ">=3.12"
dependencies = [
    "boto3>=1.34.0",
    "requests>=2.31",
    "sqlalchemy>=2.0.0",
    "psycopg2-binary>=2.9.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["gpu_worker*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`gpu-worker/gpu_worker/__init__.py`: empty. `gpu-worker/tests/__init__.py`: empty.

- [ ] **Step 2: Copy the three unchanged modules**

```bash
cp transcription-worker/worker_loop.py            gpu-worker/gpu_worker/loop.py
cp transcription-worker/services/spot_watcher.py  gpu-worker/gpu_worker/spot_watcher.py
cp transcription-worker/services/ecs_metadata.py  gpu-worker/gpu_worker/ecs_metadata.py
```

No edits to their bodies.

- [ ] **Step 3: Write the failing test for the session store with an injected factory**

`gpu-worker/tests/test_session.py` — port of `transcription-worker/tests/test_gpu_session.py` with the `sys.path` / `os.environ` preamble removed and the import changed:

```python
"""GpuSessionStore never raises; it updates the row RunTask created (matched by task ARN)."""
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

from gpu_worker.session import GpuSessionStore


def make_store(row=None, raise_on_enter=False):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.one_or_none.return_value = row

    @contextmanager
    def factory():
        if raise_on_enter:
            raise RuntimeError("db down")
        yield session

    return GpuSessionStore("arn:aws:ecs:r:a:task/c/1", "i-123", session_factory=factory), session


def test_claim_fills_instance_and_processing_time():
    row = MagicMock(instance_id=None, started_processing_at=None)
    store, _ = make_store(row)
    store.claim()
    assert row.instance_id == "i-123"
    assert isinstance(row.started_processing_at, datetime)


def test_warm_until_returns_row_value():
    until = datetime(2026, 9, 1, tzinfo=timezone.utc)
    store, _ = make_store(MagicMock(warm_until=until))
    assert store.warm_until() == until


def test_close_sets_end():
    row = MagicMock(ended_at=None, end_reason=None)
    store, _ = make_store(row)
    store.close("idle")
    assert row.end_reason == "idle" and isinstance(row.ended_at, datetime)


def test_db_failure_is_swallowed():
    store, _ = make_store(raise_on_enter=True)
    store.claim()
    store.heartbeat()
    store.close("idle")
    assert store.warm_until() is None


def test_no_task_arn_is_noop():
    session = MagicMock()

    @contextmanager
    def factory():
        yield session

    store = GpuSessionStore(None, None, session_factory=factory)
    store.claim()
    session.query.assert_not_called()


def test_session_factory_is_required():
    import inspect
    params = inspect.signature(GpuSessionStore).parameters
    assert params["session_factory"].default is inspect.Parameter.empty
```

Also copy the remaining tests from the old file that are not listed above (there are more in `test_gpu_session.py`; keep every one, same edits).

- [ ] **Step 4: Run to verify it fails**

Run: `cd gpu-worker && uv run pytest tests/test_session.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gpu_worker.session'`

- [ ] **Step 5: Write `db.py` and `session.py`**

`gpu-worker/gpu_worker/db.py`:

```python
"""Session factory + the one table every GPU worker touches (gpu_sessions, by task ARN).

The API owns the schema (chat-api Alembic). This model lists only the columns the
GpuSessionStore reads or writes; extra columns on the real table are ignored.
"""
from contextlib import contextmanager
from datetime import datetime
from typing import Callable, ContextManager, Generator, Optional

from sqlalchemy import DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class GpuSession(Base):
    __tablename__ = "gpu_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_arn: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    instance_id: Mapped[Optional[str]] = mapped_column(String(32))
    started_processing_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    warm_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[Optional[str]] = mapped_column(String(20))


def make_session_factory(database_url: str) -> Callable[[], ContextManager[Session]]:
    """Sync SQLAlchemy sessions from an asyncpg- or psycopg2-style URL (the API's secret is asyncpg)."""
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    engine = create_engine(sync_url, pool_pre_ping=True)
    session_local = sessionmaker(engine, autoflush=False)

    @contextmanager
    def get_session() -> Generator[Session, None, None]:
        with session_local() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    return get_session
```

`gpu-worker/gpu_worker/session.py` — copy `transcription-worker/services/gpu_session.py`, then change the imports and the constructor:

```python
from datetime import datetime, timezone
import logging

from gpu_worker.db import GpuSession

logger = logging.getLogger(__name__)


class GpuSessionStore:
    def __init__(self, task_arn: str | None, instance_id: str | None, session_factory):
        self._task_arn = task_arn
        self._instance_id = instance_id
        self._factory = session_factory
        self._warned = False
    # … every method body unchanged from services/gpu_session.py …
```

- [ ] **Step 6: Port the loop and spot-watcher tests**

`gpu-worker/tests/test_loop.py` = `transcription-worker/tests/test_worker_loop.py` with the `sys.path` preamble removed and `from worker_loop import LoopConfig, WorkerLoop` → `from gpu_worker.loop import LoopConfig, WorkerLoop`.

`gpu-worker/tests/test_spot_watcher.py` = `transcription-worker/tests/test_spot_watcher.py` with the preamble removed and `from services.spot_watcher import SpotWatcher` → `from gpu_worker.spot_watcher import SpotWatcher` (inside `make_watcher` and anywhere else it appears).

Add to `test_loop.py` (interrupt between messages was not covered):

```python
def test_interrupt_between_messages_exits_with_spot_interruption():
    clock = FakeClock()
    sessions = FakeSessions()
    interrupted = threading.Event()
    calls = []

    def receive():
        interrupted.set()          # notice arrives while the poll is empty
        return []

    loop = WorkerLoop(receive, calls.append, sessions, interrupted,
                      LoopConfig(idle_exit_seconds=900, max_lifetime_seconds=10800),
                      clock=clock.mono, wall=clock.now)
    assert loop.run() == "spot_interruption"
    assert ("close", "spot_interruption") in sessions.calls
```

- [ ] **Step 7: Run the package tests**

Run: `cd gpu-worker && uv run pytest -q`
Expected: all PASS (loop + spot watcher + session).

- [ ] **Step 8: Commit**

```bash
git add gpu-worker
git commit -m "refactor(worker): gpu-worker package — lifecycle modules shared by the GPU workers"
```

---

### Task 2: `run_sqs_worker` — the SQS consumption shell, extracted from `main.py`

**Files:**
- Create: `gpu-worker/gpu_worker/sqs.py`, `gpu-worker/tests/test_sqs.py`
- Reference: `transcription-worker/main.py` (`extend_visibility`, `process_message`, `receive_messages`, `run`)

**Interfaces:**
- Produces: `gpu_worker.sqs.Interrupted(Exception)` — a handler raises it after a spot notice; the message is left unacked.
- Produces: `gpu_worker.sqs.run_sqs_worker(*, queue_url: str, region: str, handlers: dict[str, Callable[[dict, dict], None]], session_store: GpuSessionStore, idle_exit_seconds: int, max_lifetime_seconds: int, visibility_timeout: int = 600, visibility_extension_interval: int = 300, sqs_client=None, watcher_factory=SpotWatcher, idle_watcher_factory=SpotWatcher.idle_watcher) -> str`. Handlers receive `(body: dict, message: dict)`. Returns the loop's end reason. The store is claimed/heartbeated/closed by `WorkerLoop` exactly as today.

- [ ] **Step 1: Write the failing tests**

`gpu-worker/tests/test_sqs.py`:

```python
"""run_sqs_worker: dispatch by body.type, delete only on success, never on Interrupted."""
import json
import threading
from unittest.mock import MagicMock

import pytest

from gpu_worker.sqs import Interrupted, run_sqs_worker


class FakeStore:
    def __init__(self):
        self.calls = []
    def claim(self): self.calls.append("claim")
    def heartbeat(self): self.calls.append("heartbeat")
    def warm_until(self): return None
    def close(self, end_reason): self.calls.append(("close", end_reason))


class FakeWatcher:
    interrupted = threading.Event()
    def __init__(self, *a, **k): pass
    @classmethod
    def idle_watcher(cls, region): return cls()
    def start(self): pass
    def stop(self): pass


def make_sqs(bodies):
    """Serve each body once, then empty polls forever."""
    sqs = MagicMock()
    queue = [[{"Body": json.dumps(b), "ReceiptHandle": f"rh-{i}"}] for i, b in enumerate(bodies)]
    sqs.receive_message.side_effect = lambda **kw: {"Messages": queue.pop(0)} if queue else {}
    return sqs


def run(bodies, handlers, idle_exit_seconds=0):
    FakeWatcher.interrupted.clear()
    sqs = make_sqs(bodies)
    store = FakeStore()
    reason = run_sqs_worker(
        queue_url="https://sqs.test/q", region="us-east-1", handlers=handlers,
        session_store=store, idle_exit_seconds=idle_exit_seconds, max_lifetime_seconds=10800,
        sqs_client=sqs, watcher_factory=FakeWatcher, idle_watcher_factory=FakeWatcher.idle_watcher,
    )
    return reason, sqs, store


def test_dispatches_by_type_and_deletes_on_success():
    seen = []
    reason, sqs, store = run([{"type": "a", "x": 1}], {"a": lambda body, msg: seen.append(body)})
    assert seen == [{"type": "a", "x": 1}]
    sqs.delete_message.assert_called_once()
    assert sqs.delete_message.call_args.kwargs["ReceiptHandle"] == "rh-0"
    assert reason == "idle" and store.calls[0] == "claim" and ("close", "idle") in store.calls


def test_handler_exception_leaves_message_for_retry():
    def boom(body, msg): raise RuntimeError("x")
    _, sqs, _ = run([{"type": "a"}], {"a": boom})
    sqs.delete_message.assert_not_called()


def test_interrupted_leaves_message_and_exits():
    def interrupt(body, msg):
        FakeWatcher.interrupted.set()
        raise Interrupted()
    reason, sqs, _ = run([{"type": "a"}, {"type": "a"}], {"a": interrupt}, idle_exit_seconds=900)
    sqs.delete_message.assert_not_called()
    assert reason == "spot_interruption"
    assert sqs.receive_message.call_count == 1   # exited before the second message


def test_unknown_type_is_not_deleted():
    _, sqs, _ = run([{"type": "nope"}], {"a": lambda b, m: None})
    sqs.delete_message.assert_not_called()


def test_receive_uses_long_poll_of_one():
    _, sqs, _ = run([], {})
    kw = sqs.receive_message.call_args.kwargs
    assert kw["MaxNumberOfMessages"] == 1 and kw["WaitTimeSeconds"] == 20
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd gpu-worker && uv run pytest tests/test_sqs.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gpu_worker.sqs'`

- [ ] **Step 3: Implement `sqs.py`**

```python
"""SQS consumption shell shared by the GPU workers.

One message at a time; a background thread extends visibility while a handler runs; a
SpotWatcher releases the in-flight message on a 2-minute interruption notice; WorkerLoop
decides when the process exits (idle, max lifetime, interruption) and keeps the gpu_sessions
ledger. Handlers receive (body, message). A handler that returns acks the message; one that
raises leaves it for redelivery — including Interrupted, which the SpotWatcher has already
released with VisibilityTimeout=0.
"""
import json
import logging
import threading
from typing import Callable

import boto3

from gpu_worker.loop import LoopConfig, WorkerLoop
from gpu_worker.spot_watcher import SpotWatcher

logger = logging.getLogger(__name__)

Handler = Callable[[dict, dict], None]


class Interrupted(Exception):
    """Raised by a handler that stopped because a spot interruption notice arrived."""


def run_sqs_worker(
    *,
    queue_url: str,
    region: str,
    handlers: dict[str, Handler],
    session_store,
    idle_exit_seconds: int,
    max_lifetime_seconds: int,
    visibility_timeout: int = 600,
    visibility_extension_interval: int = 300,
    sqs_client=None,
    watcher_factory=SpotWatcher,
    idle_watcher_factory=SpotWatcher.idle_watcher,
) -> str:
    sqs = sqs_client or boto3.client("sqs", region_name=region)
    interrupted = watcher_factory.interrupted

    def extend_visibility(receipt_handle: str, stop: threading.Event) -> None:
        while not stop.wait(visibility_extension_interval):
            try:
                sqs.change_message_visibility(
                    QueueUrl=queue_url, ReceiptHandle=receipt_handle, VisibilityTimeout=visibility_timeout
                )
            except Exception:
                logger.warning("Failed to extend message visibility", exc_info=True)

    def receive() -> list:
        return sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=20).get("Messages", [])

    def process(message: dict) -> None:
        body = json.loads(message["Body"])
        msg_type = body.get("type")
        handler = handlers.get(msg_type)
        receipt_handle = message["ReceiptHandle"]
        if handler is None:
            logger.error("Unknown message type %r — leaving for redelivery", msg_type)
            return
        stop = threading.Event()
        threading.Thread(target=extend_visibility, args=(receipt_handle, stop), daemon=True).start()
        watcher = watcher_factory(queue_url, receipt_handle, region)
        watcher.start()
        try:
            handler(body, message)
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
            logger.info("Message type=%s processed and deleted", msg_type)
        except Interrupted:
            logger.warning("Message type=%s interrupted — released to the queue", msg_type)
        except Exception:
            logger.error("Message type=%s failed; will retry via SQS", msg_type, exc_info=True)
        finally:
            stop.set()
            watcher.stop()

    idle_watcher = idle_watcher_factory(region)
    idle_watcher.start()
    try:
        loop = WorkerLoop(
            receive=receive, process=process, sessions=session_store, interrupted=interrupted,
            config=LoopConfig(idle_exit_seconds=idle_exit_seconds, max_lifetime_seconds=max_lifetime_seconds),
        )
        return loop.run()
    finally:
        idle_watcher.stop()
```

- [ ] **Step 4: Run the tests**

Run: `cd gpu-worker && uv run pytest -q`
Expected: all PASS (`WorkerLoop._check_exit_conditions` returns the literal `"spot_interruption"`).

- [ ] **Step 5: Commit**

```bash
git add gpu-worker
git commit -m "feat(worker): run_sqs_worker — shared SQS shell with Interrupted semantics"
```

---

### Task 3: Transcription worker consumes `gpu-worker`

**Files:**
- Modify: `transcription-worker/main.py`, `transcription-worker/models.py`, `transcription-worker/Dockerfile`, `transcription-worker/pyproject.toml`, `transcription-worker/CLAUDE.md`, `.github/workflows/worker.yml`
- Delete: `transcription-worker/worker_loop.py`, `transcription-worker/services/gpu_session.py`, `transcription-worker/services/spot_watcher.py`, `transcription-worker/services/ecs_metadata.py`, `transcription-worker/tests/test_worker_loop.py`, `transcription-worker/tests/test_spot_watcher.py`, `transcription-worker/tests/test_gpu_session.py`

**Interfaces:**
- Consumes: `gpu_worker.sqs.run_sqs_worker`, `gpu_worker.session.GpuSessionStore`, `gpu_worker.db.make_session_factory`, `gpu_worker.ecs_metadata.{task_arn,instance_id}`.

- [ ] **Step 1: Rewrite `main.py`**

Keep the torchaudio / huggingface patches and the logging setup verbatim; replace everything from `sqs = boto3.client(...)` to the end with:

```python
from config import Settings
from handlers.transcription import process_transcription_job
from handlers.embedding import process_sample_embedding
from gpu_worker.db import make_session_factory
from gpu_worker.ecs_metadata import instance_id, task_arn
from gpu_worker.session import GpuSessionStore
from gpu_worker.sqs import run_sqs_worker

settings = Settings()

# Existing handlers take (body, settings); the shell passes (body, message).
HANDLERS = {
    "transcription_job": lambda body, _msg: process_transcription_job(body, settings),
    "sample_embedding": lambda body, _msg: process_sample_embedding(body, settings),
}


def run() -> None:
    logger.info("Transcription worker started (idle_exit=%ss, max_lifetime=%ss)",
                settings.IDLE_EXIT_SECONDS, settings.MAX_LIFETIME_SECONDS)
    run_sqs_worker(
        queue_url=settings.TRANSCRIBE_SQS_QUEUE_URL,
        region=settings.AWS_REGION,
        handlers=HANDLERS,
        session_store=GpuSessionStore(task_arn(), instance_id(), make_session_factory(settings.DATABASE_URL)),
        idle_exit_seconds=settings.IDLE_EXIT_SECONDS,
        max_lifetime_seconds=settings.MAX_LIFETIME_SECONDS,
        visibility_timeout=settings.SQS_VISIBILITY_TIMEOUT,
        visibility_extension_interval=settings.SQS_VISIBILITY_EXTENSION_INTERVAL,
    )


if __name__ == "__main__":
    run()
```

Remove the now-unused `import boto3`, `import json`, `import threading` if nothing else in the file uses them.

- [ ] **Step 2: Delete the moved files and the `GpuSession` model**

```bash
git rm transcription-worker/worker_loop.py transcription-worker/services/gpu_session.py \
       transcription-worker/services/spot_watcher.py transcription-worker/services/ecs_metadata.py \
       transcription-worker/tests/test_worker_loop.py transcription-worker/tests/test_spot_watcher.py \
       transcription-worker/tests/test_gpu_session.py
```

In `transcription-worker/models.py` delete the `class GpuSession(Base)` block (line ~158 to the end of the class). `grep -rn "GpuSession\|worker_loop\|spot_watcher\|ecs_metadata\|gpu_session" transcription-worker --include=*.py` must return nothing.

- [ ] **Step 3: Dependencies and Dockerfile**

`transcription-worker/pyproject.toml` — add to `dependencies`: `"gpu-worker"`, and add:

```toml
[tool.uv.sources]
gpu-worker = { path = "../gpu-worker", editable = true }
```

`transcription-worker/Dockerfile` — the build context becomes the repo root. Change:

```dockerfile
COPY pyproject.toml .
```
to
```dockerfile
COPY gpu-worker/ /app/gpu-worker/
RUN pip install --no-cache-dir /app/gpu-worker
COPY transcription-worker/pyproject.toml .
```
and the final `COPY . .` to `COPY transcription-worker/ .`. Add a root `.dockerignore`:

```
**/.venv
**/__pycache__
**/.git
chat-vue/node_modules
chat-vue/dist
infra/**/.terraform
```

- [ ] **Step 4: Workflow**

`.github/workflows/worker.yml`: under `on.push.paths` add `- 'gpu-worker/**'`; remove `working-directory: transcription-worker` from the build step and change the `docker build` invocation's trailing `.` to `-f transcription-worker/Dockerfile .`.

- [ ] **Step 5: Run the transcription worker tests**

Run: `cd transcription-worker && uv run pytest -q`
Expected: PASS (the remaining files: aligner, embedder, matcher, transcribe_poller). Then `uv run python -c "import main"` with `DATABASE_URL=postgresql://u:p@h/x AUDIO_BUCKET_NAME=b TRANSCRIBE_SQS_QUEUE_URL=u` exported — it must import without error (torch is present in the dev venv per `CLAUDE.md`; if not, skip this check and say so).

- [ ] **Step 6: Docker build smoke (context change)**

Run: `DOCKER_BUILDKIT=1 docker build -f transcription-worker/Dockerfile -t tw-ctx-check --build-arg HUGGINGFACE_TOKEN=x . 2>&1 | grep -E "COPY|ERROR|error" | head`
Expected: the `COPY gpu-worker/` and `COPY transcription-worker/pyproject.toml` steps succeed (no `ERROR`). Once the build reaches the pyannote download step, stop it with Ctrl-C — the context change is proven; the full 7.7 GB build is CI's job. Say so in the commit message.

- [ ] **Step 7: Update `transcription-worker/CLAUDE.md`**

Replace the `test_spot_watcher.py` row in the tests table with a note: "Lifecycle (loop, spot watcher, ledger, SQS shell) lives in `../gpu-worker` — run its tests there." Add under Key Commands: `docker build -f transcription-worker/Dockerfile .` (from the repo root).

- [ ] **Step 8: Commit**

```bash
git add -A transcription-worker .github/workflows/worker.yml .dockerignore
git commit -m "refactor(worker): transcription worker consumes gpu-worker; root build context"
```

---

# Part B — `photogrammetry-worker/`

### Task 4: Scaffold, settings, model, and the subprocess runner

**Files:**
- Create: `photogrammetry-worker/pyproject.toml`, `photogrammetry-worker/config.py`, `photogrammetry-worker/models.py`, `photogrammetry-worker/pipeline/__init__.py`, `photogrammetry-worker/pipeline/runner.py`, `photogrammetry-worker/tests/__init__.py`, `photogrammetry-worker/tests/test_runner.py`

**Interfaces:**
- Produces: `config.Settings` (pydantic-settings): `DATABASE_URL: str`, `AUDIO_BUCKET_NAME: str`, `PHOTOGRAMMETRY_SQS_QUEUE_URL: str`, `AWS_REGION: str = "us-east-1"`, `IDLE_EXIT_SECONDS: int = 900`, `MAX_LIFETIME_SECONDS: int = 10800`, `PHOTOGRAMMETRY_JOB_TIMEOUT_SECONDS: int = 3600`, `SQS_VISIBILITY_TIMEOUT: int = 600`, `SQS_VISIBILITY_EXTENSION_INTERVAL: int = 300`, `WORK_DIR: str = "/tmp/pg"`, `COLMAP_USE_GPU: int = 1`.
- Produces: `models.PhotogrammetryJob` (own `Base`; columns `id: UUID`, `user_id`, `status`, `stage`, `image_count`, `input_prefix`, `mesh_s3_key`, `preview_s3_key`, `error_message`, `completed_at`, `updated_at`).
- Produces: `pipeline.runner.StageError(tool: str, message: str)` (`str(e) == message`), `pipeline.runner.JobTimeout(StageError)`, and `pipeline.runner.Runner(deadline: float, interrupted: threading.Event, clock=time.monotonic, poll_seconds=5.0)` with `run(cmd: list[str], cwd: Path, tool: str | None = None) -> str` (returns stdout; raises `StageError` on non-zero exit with the first non-empty stderr line, `JobTimeout` at the deadline, `gpu_worker.sqs.Interrupted` when the event is set — killing the child in both cases).

- [ ] **Step 1: Package files**

`photogrammetry-worker/pyproject.toml`:

```toml
[project]
name = "photogrammetry-worker"
version = "0.1.0"
description = "GPU worker: COLMAP → OpenMVS → GLB for chat.peaslee.org photogrammetry jobs"
requires-python = ">=3.12"
dependencies = [
    "gpu-worker",
    "boto3>=1.34.0",
    "pydantic-settings>=2.2.0",
    "sqlalchemy>=2.0.0",
    "psycopg2-binary>=2.9.0",
    "trimesh>=4.4",
    "pillow>=10.0",
    "numpy>=1.26",
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0"]

[tool.uv.sources]
gpu-worker = { path = "../gpu-worker", editable = true }

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`photogrammetry-worker/config.py`:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    AUDIO_BUCKET_NAME: str
    PHOTOGRAMMETRY_SQS_QUEUE_URL: str
    AWS_REGION: str = "us-east-1"
    IDLE_EXIT_SECONDS: int = 900
    MAX_LIFETIME_SECONDS: int = 10800
    PHOTOGRAMMETRY_JOB_TIMEOUT_SECONDS: int = 3600
    SQS_VISIBILITY_TIMEOUT: int = 600
    SQS_VISIBILITY_EXTENSION_INTERVAL: int = 300
    WORK_DIR: str = "/tmp/pg"
    COLMAP_USE_GPU: int = 1   # 0 runs SIFT/matching on CPU (fitlet smoke test)
```

`photogrammetry-worker/models.py`:

```python
"""photogrammetry_jobs as the worker sees it. The API owns the schema (chat-api Alembic l2m3n4o5p6q7)."""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum as SAEnum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JOB_STATUSES = ("pending", "queued", "processing", "complete", "failed")
STAGES = ("sfm", "dense", "mesh", "texture")


class Base(DeclarativeBase):
    pass


class PhotogrammetryJob(Base):
    __tablename__ = "photogrammetry_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(*JOB_STATUSES, name="photogrammetry_job_status", create_type=False), nullable=False
    )
    stage: Mapped[Optional[str]] = mapped_column(String(20))
    image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    input_prefix: Mapped[str] = mapped_column(String(1024), nullable=False)
    mesh_s3_key: Mapped[Optional[str]] = mapped_column(String(1024))
    preview_s3_key: Mapped[Optional[str]] = mapped_column(String(1024))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
```

`photogrammetry-worker/pipeline/__init__.py`, `photogrammetry-worker/tests/__init__.py`: empty.

- [ ] **Step 2: Write the failing runner tests**

`photogrammetry-worker/tests/test_runner.py`:

```python
"""Runner: stderr → StageError, deadline → JobTimeout, spot notice → Interrupted; children are killed."""
import sys
import threading
from pathlib import Path

import pytest

from gpu_worker.sqs import Interrupted
from pipeline.runner import JobTimeout, Runner, StageError

PY = sys.executable


def make(deadline_in=3600, poll=0.05):
    ev = threading.Event()
    r = Runner(deadline=__import__("time").monotonic() + deadline_in, interrupted=ev, poll_seconds=poll)
    return r, ev


def test_success_returns_stdout(tmp_path):
    r, _ = make()
    out = r.run([PY, "-c", "print('hello')"], cwd=tmp_path, tool="py")
    assert out.strip() == "hello"


def test_nonzero_exit_raises_stage_error_with_first_stderr_line(tmp_path):
    r, _ = make()
    with pytest.raises(StageError) as e:
        r.run([PY, "-c", "import sys; print('', file=sys.stderr); print('bad thing', file=sys.stderr); print('more', file=sys.stderr); sys.exit(3)"], cwd=tmp_path, tool="colmap")
    assert str(e.value) == "bad thing" and e.value.tool == "colmap"


def test_deadline_kills_and_raises_job_timeout(tmp_path):
    r, _ = make(deadline_in=0.2)
    with pytest.raises(JobTimeout):
        r.run([PY, "-c", "import time; time.sleep(10)"], cwd=tmp_path)


def test_interrupt_kills_and_raises_interrupted(tmp_path):
    r, ev = make()
    threading.Timer(0.2, ev.set).start()
    with pytest.raises(Interrupted):
        r.run([PY, "-c", "import time; time.sleep(10)"], cwd=tmp_path)


def test_tool_defaults_to_command_name(tmp_path):
    r, _ = make()
    with pytest.raises(StageError) as e:
        r.run([PY, "-c", "import sys; sys.exit(1)"], cwd=tmp_path)
    assert e.value.tool == Path(PY).name
```

- [ ] **Step 3: Run to verify failure**

Run: `cd photogrammetry-worker && uv run pytest tests/test_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.runner'`

- [ ] **Step 4: Implement `pipeline/runner.py`**

```python
"""Subprocess runner with a job deadline and a spot-interruption watch.

Every reconstruction tool runs through here so the handler can be read as a stage table.
"""
import logging
import subprocess
import threading
import time
from pathlib import Path

from gpu_worker.sqs import Interrupted

logger = logging.getLogger(__name__)


class StageError(Exception):
    def __init__(self, tool: str, message: str):
        super().__init__(message)
        self.tool = tool


class JobTimeout(StageError):
    pass


class Runner:
    def __init__(self, deadline: float, interrupted: threading.Event, clock=time.monotonic, poll_seconds: float = 5.0,
                 timeout_message: str = "Reconstruction exceeded 60 minutes"):
        self._deadline = deadline
        self._interrupted = interrupted
        self._clock = clock
        self._poll = poll_seconds
        self._timeout_message = timeout_message

    def run(self, cmd: list[str], cwd: Path, tool: str | None = None) -> str:
        tool = tool or Path(cmd[0]).name
        logger.info("[%s] %s", tool, " ".join(cmd))
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=self._poll)
                break
            except subprocess.TimeoutExpired:
                if self._interrupted.is_set():
                    self._kill(proc)
                    raise Interrupted()
                if self._clock() >= self._deadline:
                    self._kill(proc)
                    raise JobTimeout(tool, self._timeout_message)
        if proc.returncode != 0:
            first = next((line for line in stderr.splitlines() if line.strip()), f"{tool} exited with {proc.returncode}")
            logger.error("[%s] failed (%s):\n%s", tool, proc.returncode, stderr[-4000:])
            raise StageError(tool, first[:1000])
        return stdout

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        proc.kill()
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
```

- [ ] **Step 5: Run the tests**

Run: `cd photogrammetry-worker && uv run pytest -q`
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add photogrammetry-worker
git commit -m "feat(photogrammetry-worker): scaffold, settings, job model, deadline-aware subprocess runner"
```

---

### Task 5: COLMAP and OpenMVS wrappers

**Files:**
- Create: `photogrammetry-worker/pipeline/colmap.py`, `photogrammetry-worker/pipeline/openmvs.py`, `photogrammetry-worker/tests/test_colmap.py`, `photogrammetry-worker/tests/test_openmvs.py`

**Interfaces:**
- Consumes: `pipeline.runner.Runner.run(cmd, cwd, tool)`.
- Produces: `pipeline.colmap.SparseModel(path: Path, registered_images: int)`; `pipeline.colmap.sparse_reconstruct(runner, work: Path, images: Path, use_gpu: bool) -> SparseModel`; `pipeline.colmap.undistort(runner, work: Path, images: Path, model: SparseModel) -> Path` (returns the dense workspace dir `work/dense`).
- Produces: `pipeline.openmvs.interface(runner, dense: Path) -> Path` (`scene.mvs`), `densify(runner, dense: Path, scene: Path) -> Path` (`scene_dense.mvs`), `reconstruct_mesh(runner, dense, scene_dense) -> Path` (`scene_dense_mesh.ply`), `refine_mesh(runner, dense, scene_dense, mesh_ply) -> Path` (`scene_dense_mesh_refine.ply`), `texture_mesh(runner, dense, scene_dense, mesh_ply) -> Path` (`scene_textured.obj`).

- [ ] **Step 1: Write the failing COLMAP tests**

`photogrammetry-worker/tests/test_colmap.py`:

```python
"""COLMAP wrapper: command shape, model selection by registered images, GPU flag."""
from pathlib import Path

from pipeline.colmap import SparseModel, sparse_reconstruct, undistort


class FakeRunner:
    """Records commands; `model_analyzer` output comes from `analyses` keyed by model dir name."""
    def __init__(self, analyses):
        self.cmds = []
        self.analyses = analyses

    def run(self, cmd, cwd, tool=None):
        self.cmds.append(cmd)
        if cmd[1] == "model_analyzer":
            name = Path(cmd[cmd.index("--path") + 1]).name
            return f"Cameras: 1\nImages: 22\nRegistered images: {self.analyses[name]}\nPoints: 100\n"
        return ""


def make_sparse(work, names):
    for n in names:
        (work / "sparse" / n).mkdir(parents=True)


def test_sparse_reconstruct_runs_extract_match_map_with_gpu_flags(tmp_path):
    make_sparse(tmp_path, ["0"])
    r = FakeRunner({"0": 20})
    model = sparse_reconstruct(r, tmp_path, tmp_path / "images", use_gpu=False)
    subcommands = [c[1] for c in r.cmds]
    assert subcommands[:3] == ["feature_extractor", "exhaustive_matcher", "mapper"]
    assert "--SiftExtraction.use_gpu" in r.cmds[0] and r.cmds[0][r.cmds[0].index("--SiftExtraction.use_gpu") + 1] == "0"
    assert "--SiftMatching.use_gpu" in r.cmds[1]
    assert "--ImageReader.single_camera" in r.cmds[0]
    assert model == SparseModel(path=tmp_path / "sparse" / "0", registered_images=20)


def test_picks_model_with_most_registered_images(tmp_path):
    make_sparse(tmp_path, ["0", "1", "2"])
    r = FakeRunner({"0": 5, "1": 17, "2": 9})
    model = sparse_reconstruct(r, tmp_path, tmp_path / "images", use_gpu=True)
    assert model.path.name == "1" and model.registered_images == 17


def test_no_model_means_zero_registered(tmp_path):
    (tmp_path / "sparse").mkdir()
    r = FakeRunner({})
    model = sparse_reconstruct(r, tmp_path, tmp_path / "images", use_gpu=True)
    assert model.registered_images == 0


def test_undistort_writes_dense_workspace(tmp_path):
    r = FakeRunner({})
    dense = undistort(r, tmp_path, tmp_path / "images", SparseModel(tmp_path / "sparse" / "0", 10))
    cmd = r.cmds[0]
    assert cmd[1] == "image_undistorter" and dense == tmp_path / "dense"
    assert cmd[cmd.index("--output_type") + 1] == "COLMAP"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd photogrammetry-worker && uv run pytest tests/test_colmap.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.colmap'`

- [ ] **Step 3: Implement `pipeline/colmap.py`**

```python
"""COLMAP: sparse reconstruction (the `sfm` stage) and undistortion for OpenMVS."""
import re
from dataclasses import dataclass
from pathlib import Path

_REGISTERED = re.compile(r"Registered images:\s*(\d+)")


@dataclass(frozen=True)
class SparseModel:
    path: Path
    registered_images: int


def sparse_reconstruct(runner, work: Path, images: Path, use_gpu: bool) -> SparseModel:
    db = work / "database.db"
    sparse = work / "sparse"
    sparse.mkdir(parents=True, exist_ok=True)
    gpu = "1" if use_gpu else "0"
    runner.run([
        "colmap", "feature_extractor", "--database_path", str(db), "--image_path", str(images),
        "--ImageReader.camera_model", "SIMPLE_RADIAL", "--ImageReader.single_camera", "1",
        "--SiftExtraction.use_gpu", gpu,
    ], cwd=work, tool="colmap feature_extractor")
    runner.run([
        "colmap", "exhaustive_matcher", "--database_path", str(db), "--SiftMatching.use_gpu", gpu,
    ], cwd=work, tool="colmap exhaustive_matcher")
    runner.run([
        "colmap", "mapper", "--database_path", str(db), "--image_path", str(images), "--output_path", str(sparse),
    ], cwd=work, tool="colmap mapper")
    best = SparseModel(sparse / "0", 0)
    for model_dir in sorted(p for p in sparse.iterdir() if p.is_dir()):
        out = runner.run(["colmap", "model_analyzer", "--path", str(model_dir)], cwd=work, tool="colmap model_analyzer")
        m = _REGISTERED.search(out)
        n = int(m.group(1)) if m else 0
        if n > best.registered_images:
            best = SparseModel(model_dir, n)
    return best


def undistort(runner, work: Path, images: Path, model: SparseModel) -> Path:
    dense = work / "dense"
    runner.run([
        "colmap", "image_undistorter", "--image_path", str(images), "--input_path", str(model.path),
        "--output_path", str(dense), "--output_type", "COLMAP",
    ], cwd=work, tool="colmap image_undistorter")
    return dense
```

- [ ] **Step 4: Write the failing OpenMVS tests**

`photogrammetry-worker/tests/test_openmvs.py`:

```python
"""OpenMVS wrapper: each step names its tool, runs in the dense workspace, returns the next file."""
from pipeline.openmvs import densify, interface, reconstruct_mesh, refine_mesh, texture_mesh


class FakeRunner:
    def __init__(self): self.calls = []
    def run(self, cmd, cwd, tool=None):
        self.calls.append((cmd, cwd, tool)); return ""


def test_chain_produces_expected_paths(tmp_path):
    r = FakeRunner()
    dense = tmp_path / "dense"
    scene = interface(r, dense)
    scene_dense = densify(r, dense, scene)
    mesh = reconstruct_mesh(r, dense, scene_dense)
    refined = refine_mesh(r, dense, scene_dense, mesh)
    obj = texture_mesh(r, dense, scene_dense, refined)
    assert [c[0][0] for c in r.calls] == ["InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh", "RefineMesh", "TextureMesh"]
    assert all(c[1] == dense for c in r.calls)
    assert scene == dense / "scene.mvs" and scene_dense == dense / "scene_dense.mvs"
    assert mesh == dense / "scene_dense_mesh.ply" and refined == dense / "scene_dense_mesh_refine.ply"
    assert obj == dense / "scene_textured.obj"


def test_densify_uses_resolution_level_2(tmp_path):
    r = FakeRunner()
    densify(r, tmp_path, tmp_path / "scene.mvs")
    cmd = r.calls[0][0]
    assert cmd[cmd.index("--resolution-level") + 1] == "2"


def test_texture_exports_obj(tmp_path):
    r = FakeRunner()
    texture_mesh(r, tmp_path, tmp_path / "scene_dense.mvs", tmp_path / "m.ply")
    cmd = r.calls[0][0]
    assert cmd[cmd.index("--export-type") + 1] == "obj"
```

- [ ] **Step 5: Implement `pipeline/openmvs.py`**

```python
"""OpenMVS: dense → mesh → (refine) → texture. Every step runs inside the COLMAP dense workspace."""
from pathlib import Path


def interface(runner, dense: Path) -> Path:
    out = dense / "scene.mvs"
    runner.run(["InterfaceCOLMAP", "-i", str(dense), "-o", str(out), "-w", str(dense)], cwd=dense, tool="InterfaceCOLMAP")
    return out


def densify(runner, dense: Path, scene: Path) -> Path:
    out = dense / "scene_dense.mvs"
    runner.run(["DensifyPointCloud", str(scene), "-w", str(dense), "-o", str(out), "--resolution-level", "2"],
               cwd=dense, tool="DensifyPointCloud")
    return out


def reconstruct_mesh(runner, dense: Path, scene_dense: Path) -> Path:
    out = dense / "scene_dense_mesh.mvs"
    runner.run(["ReconstructMesh", str(scene_dense), "-w", str(dense), "-o", str(out)], cwd=dense, tool="ReconstructMesh")
    return dense / "scene_dense_mesh.ply"


def refine_mesh(runner, dense: Path, scene_dense: Path, mesh_ply: Path) -> Path:
    out = dense / "scene_dense_mesh_refine.mvs"
    runner.run(["RefineMesh", str(scene_dense), "-m", str(mesh_ply), "-w", str(dense), "-o", str(out)],
               cwd=dense, tool="RefineMesh")
    return dense / "scene_dense_mesh_refine.ply"


def texture_mesh(runner, dense: Path, scene_dense: Path, mesh_ply: Path) -> Path:
    out = dense / "scene_textured.mvs"
    runner.run(["TextureMesh", str(scene_dense), "-m", str(mesh_ply), "-w", str(dense), "-o", str(out),
                "--export-type", "obj"], cwd=dense, tool="TextureMesh")
    return dense / "scene_textured.obj"
```

The output file names (`<name>.ply` beside `<name>.mvs`, `<name>.obj` for `--export-type obj`) are OpenMVS v2.x behaviour; Task 8's CPU smoke run confirms them against the real binaries — if a name differs, fix it here and in the test, nowhere else.

- [ ] **Step 6: Run the tests**

Run: `cd photogrammetry-worker && uv run pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add photogrammetry-worker
git commit -m "feat(photogrammetry-worker): COLMAP and OpenMVS wrappers"
```

---

### Task 6: Export — GLB via trimesh, preview via Pillow; S3 client

**Files:**
- Create: `photogrammetry-worker/pipeline/export.py`, `photogrammetry-worker/services/__init__.py`, `photogrammetry-worker/services/s3.py`, `photogrammetry-worker/tests/test_export.py`, `photogrammetry-worker/tests/test_s3.py`

**Interfaces:**
- Produces: `pipeline.export.obj_to_glb(obj: Path, out: Path) -> Path`; `pipeline.export.make_preview(image: Path, out: Path, max_edge: int = 640) -> Path`.
- Produces: `services.s3.S3Client(bucket: str, region: str, client=None)` with `list_keys(prefix: str) -> list[str]` (paginated, sorted), `download(key: str, dest: Path) -> None`, `upload_file(path: Path, key: str, content_type: str) -> None`.

- [ ] **Step 1: Write the failing export tests**

`photogrammetry-worker/tests/test_export.py`:

```python
"""GLB export from a textured OBJ; preview downscale keeps aspect."""
from pathlib import Path

import trimesh
from PIL import Image

from pipeline.export import make_preview, obj_to_glb


def write_textured_quad(d: Path) -> Path:
    Image.new("RGB", (2, 2), (255, 0, 0)).save(d / "tex.png")
    (d / "quad.mtl").write_text("newmtl m\nKd 1 1 1\nmap_Kd tex.png\n")
    (d / "quad.obj").write_text(
        "mtllib quad.mtl\n"
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
        "usemtl m\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n"
    )
    return d / "quad.obj"


def test_obj_to_glb_writes_binary_gltf_with_texture(tmp_path):
    obj = write_textured_quad(tmp_path)
    out = obj_to_glb(obj, tmp_path / "mesh.glb")
    data = out.read_bytes()
    assert data[:4] == b"glTF"
    mesh = trimesh.load(out, force="mesh")
    assert len(mesh.faces) == 2
    assert getattr(mesh.visual, "material", None) is not None


def test_make_preview_downscales_long_edge_and_keeps_aspect(tmp_path):
    Image.new("RGB", (1600, 1200), (0, 255, 0)).save(tmp_path / "in.jpg")
    out = make_preview(tmp_path / "in.jpg", tmp_path / "preview.png", max_edge=640)
    with Image.open(out) as im:
        assert im.size == (640, 480) and im.format == "PNG"


def test_make_preview_does_not_upscale(tmp_path):
    Image.new("RGB", (300, 200)).save(tmp_path / "in.png")
    out = make_preview(tmp_path / "in.png", tmp_path / "preview.png")
    with Image.open(out) as im:
        assert im.size == (300, 200)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd photogrammetry-worker && uv run pytest tests/test_export.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.export'`

- [ ] **Step 3: Implement `pipeline/export.py`**

```python
"""Final outputs: GLB from the textured OBJ (trimesh, no GPU/EGL) and a PNG preview from a photo."""
from pathlib import Path

import trimesh
from PIL import Image, ImageOps


def obj_to_glb(obj: Path, out: Path) -> Path:
    mesh = trimesh.load(obj, force="mesh")
    out.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(out, file_type="glb")
    return out


def make_preview(image: Path, out: Path, max_edge: int = 640) -> Path:
    with Image.open(image) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_edge, max_edge))   # never upscales, keeps aspect
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out, format="PNG")
    return out
```

- [ ] **Step 4: Write the failing S3 tests**

`photogrammetry-worker/tests/test_s3.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock

from services.s3 import S3Client


def make():
    client = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "p/0002.jpg"}, {"Key": "p/0001.jpg"}]},
        {"Contents": [{"Key": "p/0003.png"}]},
        {},
    ]
    client.get_paginator.return_value = paginator
    return S3Client("bucket", "us-east-1", client=client), client


def test_list_keys_paginates_and_sorts():
    s3, client = make()
    assert s3.list_keys("p/") == ["p/0001.jpg", "p/0002.jpg", "p/0003.png"]
    client.get_paginator.assert_called_with("list_objects_v2")


def test_download_creates_parent(tmp_path):
    s3, client = make()
    s3.download("p/0001.jpg", tmp_path / "images" / "0001.jpg")
    client.download_file.assert_called_once_with("bucket", "p/0001.jpg", str(tmp_path / "images" / "0001.jpg"))
    assert (tmp_path / "images").is_dir()


def test_upload_sets_content_type(tmp_path):
    s3, client = make()
    f = tmp_path / "mesh.glb"; f.write_bytes(b"glTF")
    s3.upload_file(f, "out/mesh.glb", "model/gltf-binary")
    client.upload_file.assert_called_once_with(str(f), "bucket", "out/mesh.glb", ExtraArgs={"ContentType": "model/gltf-binary"})
```

- [ ] **Step 5: Implement `services/s3.py`**

```python
from pathlib import Path

import boto3


class S3Client:
    def __init__(self, bucket: str, region: str, client=None):
        self.bucket = bucket
        self._c = client or boto3.client("s3", region_name=region)

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        for page in self._c.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(o["Key"] for o in page.get("Contents", []))
        return sorted(keys)

    def download(self, key: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._c.download_file(self.bucket, key, str(dest))

    def upload_file(self, path: Path, key: str, content_type: str) -> None:
        self._c.upload_file(str(path), self.bucket, key, ExtraArgs={"ContentType": content_type})
```

`services/__init__.py`: empty.

- [ ] **Step 6: Run the tests**

Run: `cd photogrammetry-worker && uv run pytest -q`
Expected: all PASS (trimesh's GLB export of a textured mesh needs `pillow` — already a dependency).

- [ ] **Step 7: Commit**

```bash
git add photogrammetry-worker
git commit -m "feat(photogrammetry-worker): GLB/preview export and S3 client"
```

---

### Task 7: The reconstruction pipeline object and the job handler

**Files:**
- Create: `photogrammetry-worker/pipeline/reconstruct.py`, `photogrammetry-worker/handlers/__init__.py`, `photogrammetry-worker/handlers/photogrammetry.py`, `photogrammetry-worker/tests/test_handler.py`

**Interfaces:**
- Consumes: `pipeline.colmap.*`, `pipeline.openmvs.*`, `pipeline.export.*`, `pipeline.runner.{Runner,StageError}`, `services.s3.S3Client`, `models.PhotogrammetryJob`, `gpu_worker.sqs.Interrupted`.
- Produces: `pipeline.reconstruct.Reconstruction(runner, work: Path, use_gpu: bool)` with `sfm(images: Path) -> SparseModel`, `dense(images: Path, model: SparseModel) -> Path`, `mesh(dense: Path, refine: bool) -> Path`, `texture(dense: Path, mesh_ply: Path) -> Path`.
- Produces: `handlers.photogrammetry.Deps(session_factory, s3, reconstruction_factory: Callable[[Path, float], Reconstruction], work_root: Path, use_gpu: bool, job_timeout_seconds: int, clock=time.monotonic)` and `process_photogrammetry_job(body: dict, deps: Deps) -> None`.

- [ ] **Step 1: `pipeline/reconstruct.py`**

```python
"""The four stages as one object so the handler can be tested with a fake."""
from pathlib import Path

from pipeline import colmap, openmvs
from pipeline.colmap import SparseModel


class Reconstruction:
    def __init__(self, runner, work: Path, use_gpu: bool):
        self._r = runner
        self._work = work
        self._gpu = use_gpu

    def sfm(self, images: Path) -> SparseModel:
        return colmap.sparse_reconstruct(self._r, self._work, images, self._gpu)

    def dense(self, images: Path, model: SparseModel) -> Path:
        dense = colmap.undistort(self._r, self._work, images, model)
        scene = openmvs.interface(self._r, dense)
        openmvs.densify(self._r, dense, scene)
        return dense

    def mesh(self, dense: Path, refine: bool) -> Path:
        scene_dense = dense / "scene_dense.mvs"
        ply = openmvs.reconstruct_mesh(self._r, dense, scene_dense)
        if refine:
            ply = openmvs.refine_mesh(self._r, dense, scene_dense, ply)
        return ply

    def texture(self, dense: Path, mesh_ply: Path) -> Path:
        return openmvs.texture_mesh(self._r, dense, dense / "scene_dense.mvs", mesh_ply)
```

- [ ] **Step 2: Write the failing handler tests**

`photogrammetry-worker/tests/test_handler.py`:

```python
"""Handler walks the stages, writes outputs under the job's own prefix, and maps failures per spec §1."""
import math
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from gpu_worker.sqs import Interrupted
from handlers.photogrammetry import Deps, process_photogrammetry_job
from pipeline.colmap import SparseModel
from pipeline.runner import StageError

USER = "user-1"


class FakeRecon:
    """Records stage calls; `registered` drives the threshold; `fail_at` raises in that stage."""
    def __init__(self, work, registered=10, fail_at=None, interrupt_at=None):
        self.work, self.registered, self.fail_at, self.interrupt_at = work, registered, fail_at, interrupt_at
        self.calls = []

    def _step(self, name):
        self.calls.append(name)
        if name == self.interrupt_at: raise Interrupted()
        if name == self.fail_at: raise StageError("tool", f"{name} exploded")

    def sfm(self, images):
        self._step("sfm"); return SparseModel(self.work / "sparse" / "0", self.registered)
    def dense(self, images, model):
        self._step("dense"); d = self.work / "dense"; d.mkdir(parents=True, exist_ok=True); return d
    def mesh(self, dense, refine):
        self._step(("mesh", refine)); return dense / "m.ply"
    def texture(self, dense, ply):
        self._step("texture")
        Image.new("RGB", (2, 2)).save(dense / "tex.png")
        (dense / "scene_textured.mtl").write_text("newmtl m\nmap_Kd tex.png\n")
        obj = dense / "scene_textured.obj"
        obj.write_text("mtllib scene_textured.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nusemtl m\nf 1/1 2/2 3/3\n")
        return obj


class FakeS3:
    def __init__(self, keys):
        self.keys, self.uploaded = keys, []
    def list_keys(self, prefix): return [k for k in self.keys if k.startswith(prefix)]
    def download(self, key, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (800, 600)).save(dest)
    def upload_file(self, path, key, content_type): self.uploaded.append((key, content_type, Path(path).stat().st_size > 0))


def make(tmp_path, *, status="queued", image_count=10, keys=None, recon_kwargs=None):
    job_id = uuid.uuid4()
    prefix = f"photogrammetry/{USER}/{job_id}/input/"
    keys = keys if keys is not None else [f"{prefix}{i:04d}.jpg" for i in range(1, image_count + 1)]
    job = MagicMock(id=job_id, user_id=USER, status=status, stage=None, image_count=image_count,
                    input_prefix=prefix, mesh_s3_key=None, preview_s3_key=None, error_message=None, completed_at=None)
    session = MagicMock()
    session.get.return_value = job

    @contextmanager
    def factory():
        yield session

    recons = []
    def recon_factory(work, deadline):
        r = FakeRecon(work, **(recon_kwargs or {})); recons.append(r); return r

    s3 = FakeS3(keys)
    deps = Deps(session_factory=factory, s3=s3, reconstruction_factory=recon_factory,
                work_root=tmp_path / "work", use_gpu=False, job_timeout_seconds=3600)
    return job, s3, recons, deps


def test_happy_path_walks_stages_and_writes_outputs_under_job_prefix(tmp_path):
    job, s3, recons, deps = make(tmp_path)
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert recons[0].calls == ["sfm", "dense", ("mesh", True), "texture"]
    assert job.status == "complete" and job.stage is None and isinstance(job.completed_at, datetime)
    assert job.mesh_s3_key == f"photogrammetry/{USER}/{job.id}/output/mesh.glb"
    assert job.preview_s3_key == f"photogrammetry/{USER}/{job.id}/output/preview.png"
    assert sorted(k for k, _, ok in s3.uploaded if ok) == [job.mesh_s3_key, job.preview_s3_key]
    assert dict((k, ct) for k, ct, _ in s3.uploaded)[job.mesh_s3_key] == "model/gltf-binary"
    assert not (tmp_path / "work" / str(job.id)).exists()   # scratch removed


def test_sample_job_outputs_go_under_job_prefix_not_input_prefix(tmp_path):
    job, s3, _, deps = make(tmp_path, keys=[f"samples/photogrammetry/images/{i:04d}.jpg" for i in range(1, 11)])
    job.input_prefix = "samples/photogrammetry/images/"
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.mesh_s3_key.startswith(f"photogrammetry/{USER}/{job.id}/output/")


def test_stage_progression_is_written_before_each_stage(tmp_path):
    job, _, recons, deps = make(tmp_path)
    seen = []
    orig = FakeRecon._step
    FakeRecon._step = lambda self, name: (seen.append(job.stage), orig(self, name))
    try:
        process_photogrammetry_job({"job_id": str(job.id)}, deps)
    finally:
        FakeRecon._step = orig
    assert seen == ["sfm", "dense", "mesh", "texture"]


def test_refine_skipped_over_100_images(tmp_path):
    job, _, recons, deps = make(tmp_path, image_count=101)
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert ("mesh", False) in recons[0].calls


def test_registration_threshold_fails_job_with_message(tmp_path):
    job, _, recons, deps = make(tmp_path, image_count=10, recon_kwargs={"registered": 5})   # < ceil(6)
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "failed" and job.error_message == "Only 5 of 10 photos could be matched — add overlap and try again"
    assert recons[0].calls == ["sfm"]


def test_threshold_boundary_passes_at_ceil(tmp_path):
    job, _, _, deps = make(tmp_path, image_count=10, recon_kwargs={"registered": 6})
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "complete"


def test_missing_uploads_fail_before_any_stage(tmp_path):
    job, _, recons, deps = make(tmp_path, image_count=10, keys=[])
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "failed" and job.error_message == "0 of 10 photos found in storage"
    assert recons == []


def test_stage_error_marks_failed_and_returns_normally(tmp_path):
    job, _, _, deps = make(tmp_path, recon_kwargs={"fail_at": "dense"})
    process_photogrammetry_job({"job_id": str(job.id)}, deps)     # no raise → message acked
    assert job.status == "failed" and job.error_message == "dense exploded" and job.stage is None


def test_interrupt_resets_to_queued_and_raises(tmp_path):
    job, _, _, deps = make(tmp_path, recon_kwargs={"interrupt_at": "dense"})
    with pytest.raises(Interrupted):
        process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "queued" and job.stage is None
    assert not (tmp_path / "work" / str(job.id)).exists()


def test_redelivered_terminal_job_is_skipped(tmp_path):
    job, _, recons, deps = make(tmp_path, status="complete")
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert recons == [] and job.status == "complete"


def test_processing_job_is_restarted(tmp_path):
    job, _, recons, deps = make(tmp_path, status="processing")
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert recons and job.status == "complete"


def test_unknown_job_is_skipped(tmp_path):
    job, _, recons, deps = make(tmp_path)
    with deps.session_factory() as sess:
        sess.get.return_value = None
    process_photogrammetry_job({"job_id": str(uuid.uuid4())}, deps)
    assert recons == []


def test_error_message_is_capped_at_1000_chars(tmp_path):
    job, _, _, deps = make(tmp_path, recon_kwargs={"fail_at": "sfm"})
    class LongRecon(FakeRecon):
        def sfm(self, images): raise StageError("tool", "x" * 5000)
    deps = Deps(session_factory=deps.session_factory, s3=deps.s3,
                reconstruction_factory=lambda work, deadline: LongRecon(work),
                work_root=deps.work_root, use_gpu=False, job_timeout_seconds=3600)
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert len(job.error_message) == 1000
```

- [ ] **Step 3: Run to verify failure**

Run: `cd photogrammetry-worker && uv run pytest tests/test_handler.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'handlers.photogrammetry'`

- [ ] **Step 4: Implement `handlers/photogrammetry.py`**

```python
"""One photogrammetry job: fetch → sfm → dense → mesh → texture → publish.

Failure mapping (spec §1): StageError/JobTimeout/any Exception → row `failed`, return normally
(the SQS shell acks). Interrupted → row back to `queued`, re-raise (not acked; the SpotWatcher
already released the message). Scratch is removed in every case.
"""
import logging
import math
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from gpu_worker.sqs import Interrupted
from models import PhotogrammetryJob
from pipeline.export import make_preview, obj_to_glb
from pipeline.runner import StageError

logger = logging.getLogger(__name__)

RESTARTABLE = ("queued", "processing")
REGISTRATION_MIN_FRACTION = 0.6
REFINE_MAX_IMAGES = 100
ERROR_MAX_CHARS = 1000


@dataclass
class Deps:
    session_factory: Callable
    s3: object
    reconstruction_factory: Callable[[Path, float], object]   # (work_dir, deadline_monotonic) -> Reconstruction
    work_root: Path
    use_gpu: bool
    job_timeout_seconds: int
    clock: Callable[[], float] = field(default=time.monotonic)


def _update(deps: Deps, job_id: uuid.UUID, **values) -> None:
    with deps.session_factory() as s:
        job = s.get(PhotogrammetryJob, job_id)
        if job is None:
            return
        for k, v in values.items():
            setattr(job, k, v)


def process_photogrammetry_job(body: dict, deps: Deps) -> None:
    job_id = uuid.UUID(body["job_id"])
    with deps.session_factory() as s:
        job = s.get(PhotogrammetryJob, job_id)
        if job is None or job.status not in RESTARTABLE:
            logger.info("Job %s skipped (status=%s)", job_id, getattr(job, "status", None))
            return
        user_id, input_prefix, image_count = job.user_id, job.input_prefix, job.image_count
        job.status, job.stage, job.error_message = "processing", "sfm", None

    work = deps.work_root / str(job_id)
    images = work / "images"
    output_prefix = f"photogrammetry/{user_id}/{job_id}/output/"
    try:
        keys = deps.s3.list_keys(input_prefix)
        if len(keys) < image_count:
            raise StageError("fetch", f"{len(keys)} of {image_count} photos found in storage")
        for key in keys:
            deps.s3.download(key, images / key.rsplit("/", 1)[-1])

        recon = deps.reconstruction_factory(work, deps.clock() + deps.job_timeout_seconds)

        model = recon.sfm(images)
        needed = math.ceil(REGISTRATION_MIN_FRACTION * image_count)
        if model.registered_images < needed:
            raise StageError("colmap mapper",
                             f"Only {model.registered_images} of {image_count} photos could be matched — add overlap and try again")

        _update(deps, job_id, stage="dense")
        dense = recon.dense(images, model)

        _update(deps, job_id, stage="mesh")
        mesh_ply = recon.mesh(dense, refine=image_count <= REFINE_MAX_IMAGES)

        _update(deps, job_id, stage="texture")
        obj = recon.texture(dense, mesh_ply)
        glb = obj_to_glb(obj, work / "mesh.glb")
        first_image = sorted(images.iterdir())[0]
        preview = make_preview(first_image, work / "preview.png")

        mesh_key, preview_key = output_prefix + "mesh.glb", output_prefix + "preview.png"
        deps.s3.upload_file(glb, mesh_key, "model/gltf-binary")
        deps.s3.upload_file(preview, preview_key, "image/png")
        _update(deps, job_id, status="complete", stage=None, mesh_s3_key=mesh_key, preview_s3_key=preview_key,
                completed_at=datetime.now(timezone.utc))
        logger.info("Job %s complete", job_id)
    except Interrupted:
        logger.warning("Job %s interrupted — back to queued", job_id)
        _update(deps, job_id, status="queued", stage=None)
        raise
    except Exception as e:   # StageError, JobTimeout, anything else deterministic
        message = str(e)[:ERROR_MAX_CHARS] or e.__class__.__name__
        logger.error("Job %s failed: %s", job_id, message, exc_info=not isinstance(e, StageError))
        _update(deps, job_id, status="failed", stage=None, error_message=message)
    finally:
        shutil.rmtree(work, ignore_errors=True)
```

`handlers/__init__.py`: empty.

- [ ] **Step 5: Run the tests**

Run: `cd photogrammetry-worker && uv run pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add photogrammetry-worker
git commit -m "feat(photogrammetry-worker): job handler — stage walk, failure mapping, outputs under the job prefix"
```

---

### Task 8: `main.py`, Dockerfile, CI workflow, CPU smoke run

**Files:**
- Create: `photogrammetry-worker/main.py`, `photogrammetry-worker/Dockerfile`, `photogrammetry-worker/CLAUDE.md`, `.github/workflows/photogrammetry-worker.yml`, `photogrammetry-worker/tests/test_main.py`

**Interfaces:**
- Consumes: everything from Tasks 2, 4, 7.
- Produces: `main.build_deps(settings) -> Deps`, `main.HANDLERS`, `main.run()`.

- [ ] **Step 1: Write the failing test for wiring**

`photogrammetry-worker/tests/test_main.py`:

```python
import os
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/x")
os.environ.setdefault("AUDIO_BUCKET_NAME", "b")
os.environ.setdefault("PHOTOGRAMMETRY_SQS_QUEUE_URL", "https://sqs.test/q")

import main  # noqa: E402
from pipeline.reconstruct import Reconstruction  # noqa: E402


def test_handlers_and_deps_wiring(tmp_path):
    assert set(main.HANDLERS) == {"photogrammetry_job"}
    with patch("main.S3Client"), patch("main.make_session_factory"):
        deps = main.build_deps(main.settings)
    recon = deps.reconstruction_factory(tmp_path, 10.0)
    assert isinstance(recon, Reconstruction)
    assert deps.job_timeout_seconds == 3600 and deps.use_gpu is True
```

- [ ] **Step 2: Implement `main.py`**

```python
import logging
from pathlib import Path

from config import Settings
from gpu_worker.db import make_session_factory
from gpu_worker.ecs_metadata import instance_id, task_arn
from gpu_worker.session import GpuSessionStore
from gpu_worker.spot_watcher import SpotWatcher
from gpu_worker.sqs import run_sqs_worker
from handlers.photogrammetry import Deps, process_photogrammetry_job
from pipeline.reconstruct import Reconstruction
from pipeline.runner import Runner
from services.s3 import S3Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

settings = Settings()


def build_deps(s: Settings) -> Deps:
    return Deps(
        session_factory=make_session_factory(s.DATABASE_URL),
        s3=S3Client(s.AUDIO_BUCKET_NAME, s.AWS_REGION),
        reconstruction_factory=lambda work, deadline: Reconstruction(
            Runner(deadline=deadline, interrupted=SpotWatcher.interrupted), work, use_gpu=bool(s.COLMAP_USE_GPU)),
        work_root=Path(s.WORK_DIR),
        use_gpu=bool(s.COLMAP_USE_GPU),
        job_timeout_seconds=s.PHOTOGRAMMETRY_JOB_TIMEOUT_SECONDS,
    )


DEPS = None
HANDLERS = {"photogrammetry_job": lambda body, _msg: process_photogrammetry_job(body, DEPS)}


def run() -> None:
    global DEPS
    DEPS = build_deps(settings)
    logger.info("Photogrammetry worker started (idle_exit=%ss, max_lifetime=%ss, job_timeout=%ss)",
                settings.IDLE_EXIT_SECONDS, settings.MAX_LIFETIME_SECONDS, settings.PHOTOGRAMMETRY_JOB_TIMEOUT_SECONDS)
    run_sqs_worker(
        queue_url=settings.PHOTOGRAMMETRY_SQS_QUEUE_URL, region=settings.AWS_REGION, handlers=HANDLERS,
        session_store=GpuSessionStore(task_arn(), instance_id(), DEPS.session_factory),
        idle_exit_seconds=settings.IDLE_EXIT_SECONDS, max_lifetime_seconds=settings.MAX_LIFETIME_SECONDS,
        visibility_timeout=settings.SQS_VISIBILITY_TIMEOUT,
        visibility_extension_interval=settings.SQS_VISIBILITY_EXTENSION_INTERVAL,
    )


if __name__ == "__main__":
    run()
```

Run: `cd photogrammetry-worker && uv run pytest -q` → all PASS.

- [ ] **Step 3: Dockerfile (multi-stage, repo-root context)**

`colmap/colmap:20260729.7651` is a **runtime** image (Ubuntu 24.04, CUDA 12.9.1, no `nvcc`), so OpenMVS
is compiled in a matching `-devel` stage and copied into the COLMAP image, which is the runtime base —
same Ubuntu, same CUDA line, so shared libraries match.

`photogrammetry-worker/Dockerfile`:

```dockerfile
# Stage 1: compile OpenMVS (CUDA) on the same Ubuntu/CUDA line as the COLMAP image.
FROM nvidia/cuda:12.9.1-devel-ubuntu24.04 AS build
ARG OPENMVS_TAG=v2.4.0
RUN apt-get update && apt-get install -y --no-install-recommends \
      git cmake build-essential ca-certificates libeigen3-dev libcgal-dev libboost-iostreams-dev \
      libboost-program-options-dev libboost-system-dev libboost-serialization-dev libopencv-dev \
      libglu1-mesa-dev libglew-dev libpng-dev libjpeg-dev libtiff-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone --depth 1 https://github.com/cdcseacave/VCG.git vcglib \
 && git clone --depth 1 --branch ${OPENMVS_TAG} https://github.com/cdcseacave/openMVS.git openMVS
RUN cmake -S openMVS -B openMVS/build -DCMAKE_BUILD_TYPE=Release -DVCG_ROOT=/src/vcglib -DOpenMVS_USE_CUDA=ON \
 && cmake --build openMVS/build -j"$(nproc)" \
 && cmake --install openMVS/build --prefix /opt/openmvs

# Stage 2: runtime = the official COLMAP image (Ubuntu 24.04, CUDA 12.9.1 runtime) + OpenMVS + Python.
FROM colmap/colmap:20260729.7651
RUN grep -q 'VERSION_ID="24.04"' /etc/os-release   # the build stage above must match this base
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.12 python3.12-venv libpython3.12 \
      libopencv-core406t64 libopencv-imgproc406t64 libopencv-imgcodecs406t64 libopencv-calib3d406t64 \
      libboost-iostreams1.83.0 libboost-program-options1.83.0 libboost-system1.83.0 libboost-serialization1.83.0 \
      libcgal-dev libgomp1 libglew2.2 libglu1-mesa libpng16-16t64 libjpeg8 libtiff6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/openmvs/bin/ /usr/local/bin/
COPY --from=build /opt/openmvs/lib/ /usr/local/lib/
RUN ldconfig && colmap -h >/dev/null && DensifyPointCloud --help >/dev/null && TextureMesh --help >/dev/null

WORKDIR /app
RUN python3.12 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
COPY gpu-worker/ /app/gpu-worker/
RUN pip install --no-cache-dir /app/gpu-worker boto3 pydantic-settings sqlalchemy psycopg2-binary "trimesh>=4.4" pillow numpy
COPY photogrammetry-worker/ /app/
CMD ["python", "main.py"]
```

The runtime `apt` package names are Ubuntu 24.04's (OpenCV 4.6 `…406t64`, Boost 1.83). The
`RUN ldconfig && … --help` line is the check: if it fails with a missing `.so`, run
`docker run --rm <build-stage-image> ldd /opt/openmvs/bin/DensifyPointCloud | grep "not found"` and add the
package that provides it (`apt-file search <lib>` in the build stage). Keep the list minimal — don't add `-dev`
packages beyond `libcgal-dev` (header-only, needed at runtime by OpenMVS's CGAL link).

- [ ] **Step 4: Build on fitlet and run the CPU smoke test**

Run (repo root; expect 30–60 min the first time):

```bash
DOCKER_BUILDKIT=1 docker build -f photogrammetry-worker/Dockerfile -t photogrammetry-worker:dev . 2>&1 | tail -20
docker run --rm photogrammetry-worker:dev colmap -h | head -3
docker run --rm photogrammetry-worker:dev TextureMesh --help | head -3
```

Expected: build succeeds; both binaries print usage.

CPU end-to-end on the committed sample (22 photos, `chat-api/app/assets/photogrammetry/images/`):

```bash
mkdir -p /tmp/pgsmoke/work /tmp/pgsmoke/images && cp chat-api/app/assets/photogrammetry/images/*.jpg /tmp/pgsmoke/images/
docker run --rm -v /tmp/pgsmoke:/tmp/pgsmoke photogrammetry-worker:dev python - <<'PY'
import threading, time
from pathlib import Path
from pipeline.reconstruct import Reconstruction
from pipeline.runner import Runner
from pipeline.export import obj_to_glb, make_preview
work, images = Path("/tmp/pgsmoke/work"), Path("/tmp/pgsmoke/images")
r = Reconstruction(Runner(time.monotonic() + 7200, threading.Event()), work, use_gpu=False)
m = r.sfm(images); print("registered", m.registered_images)
d = r.dense(images, m); ply = r.mesh(d, refine=False); obj = r.texture(d, ply)
print(obj_to_glb(obj, work / "mesh.glb").stat().st_size, make_preview(sorted(images.iterdir())[0], work / "preview.png"))
PY
```

Expected: `registered N` with N ≥ 14 (60 % of 22), a `mesh.glb` of non-trivial size, `preview.png`. This is slow on CPU (tens of minutes); it proves the tool chain and the file names in Task 5. If an OpenMVS output name differs, fix `pipeline/openmvs.py` + its test. Record the wall time and `registered` in the commit message.

- [ ] **Step 5: Workflow**

`.github/workflows/photogrammetry-worker.yml` — copy `worker.yml` and change: `name: Deploy — photogrammetry-worker`; `paths:` → `photogrammetry-worker/**`, `gpu-worker/**`, `.github/workflows/photogrammetry-worker.yml`; env `ECR_REPOSITORY: photogrammetry-prod-worker`, `TASK_FAMILY: photogrammetry-prod-worker`, `CONTAINER_NAME: photogrammetry-worker`; `role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN_PHOTOGRAMMETRY }}`; drop the `HUGGINGFACE_TOKEN` build-arg; build with `-f photogrammetry-worker/Dockerfile .` from the repo root (no `working-directory`), add `--build-arg BUILDKIT_INLINE_CACHE=1 --cache-from "$IMAGE_URI:latest"` (already there — keep).

- [ ] **Step 6: `photogrammetry-worker/CLAUDE.md`**

Sections: what it is (run-to-completion ECS task on `gpu-<env>`, launched by the API's RunTask, exits on idle), Key Commands (`uv run pytest -q`; `docker build -f photogrammetry-worker/Dockerfile .` from repo root; the CPU smoke snippet from Step 4), Environment Variables table (the `Settings` fields with defaults), Pipeline table (the stage table from spec §1), Failure mapping (three rows), and "Lifecycle lives in `../gpu-worker`".

- [ ] **Step 7: Commit**

```bash
git add photogrammetry-worker .github/workflows/photogrammetry-worker.yml
git commit -m "feat(photogrammetry-worker): main, multi-stage Dockerfile (COLMAP + OpenMVS v2.4.0), deploy workflow; CPU smoke run passed"
```

---

# Part C — `chat-api`

### Task 9: `gpu_sessions.family` — migration, model, schema

**Files:**
- Create: `chat-api/app/db/migrations/versions/m3n4o5p6q7r8_add_gpu_sessions_family.py`
- Modify: `chat-api/app/models/gpu.py`, `chat-api/app/schemas/gpu.py`
- Test: `chat-api/tests/unit/test_gpu_family_model.py`

**Interfaces:**
- Produces: `GpuSession.family: str` (String(32), server default `transcription`); `schemas.gpu.GpuFamily = Literal["transcription", "photogrammetry"]`; `GpuSessionSummary.family: str`.

- [ ] **Step 1: Failing test**

```python
"""gpu_sessions.family: column with a server default, and the summary schema carries it."""
from sqlalchemy import inspect

from app.models.gpu import GpuSession
from app.schemas.gpu import GpuFamily, GpuSessionSummary


def test_family_column_defaults_to_transcription():
    col = inspect(GpuSession).columns["family"]
    assert col.type.length == 32 and col.nullable is False
    assert col.server_default.arg == "transcription"


def test_summary_carries_family():
    s = GpuSessionSummary(started_at="2026-09-10T15:00:00Z", ended_at=None, reason="job",
                          started_by="u", end_reason=None, hours=0.5, family="photogrammetry")
    assert s.family == "photogrammetry"


def test_family_literal():
    assert set(GpuFamily.__args__) == {"transcription", "photogrammetry"}
```

Run: `cd chat-api && uv run pytest tests/unit/test_gpu_family_model.py -q` → FAIL (`KeyError: 'family'`).

- [ ] **Step 2: Model, schema, migration**

`app/models/gpu.py` — after `reason`:

```python
    family: Mapped[str] = mapped_column(String(32), nullable=False, server_default="transcription")  # transcription | photogrammetry
```

`app/schemas/gpu.py` — add `GpuFamily = Literal["transcription", "photogrammetry"]` next to `WorkerState`, and `family: str` to `GpuSessionSummary`.

Migration `m3n4o5p6q7r8_add_gpu_sessions_family.py` (revision `m3n4o5p6q7r8`, `down_revision = "l2m3n4o5p6q7"`):

```python
def upgrade() -> None:
    op.add_column("gpu_sessions", sa.Column("family", sa.String(32), nullable=False, server_default="transcription"))


def downgrade() -> None:
    op.drop_column("gpu_sessions", "family")
```

- [ ] **Step 3: Run tests and the migration round-trip**

Run: `cd chat-api && uv run pytest tests/unit -q` → all PASS.

Migration round-trip against a throwaway PostgreSQL (fitlet's native PG owns 5432, so 5433 as in the UI-spec session):

```bash
docker run -d --rm --name pgtest -e POSTGRES_PASSWORD=pw -p 5433:5432 pgvector/pgvector:pg16
sleep 5
cd chat-api && DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:5433/postgres uv run alembic upgrade head \
 && DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:5433/postgres uv run alembic downgrade -1 \
 && DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:5433/postgres uv run alembic upgrade head
docker stop pgtest
```

Expected: three runs without error; the `upgrade` log's last line names `m3n4o5p6q7r8`.

- [ ] **Step 4: Commit**

```bash
git add chat-api/app/models/gpu.py chat-api/app/schemas/gpu.py chat-api/app/db/migrations/versions/m3n4o5p6q7r8_add_gpu_sessions_family.py chat-api/tests/unit/test_gpu_family_model.py
git commit -m "feat(api): gpu_sessions.family column (migration m3n4o5p6q7r8), GpuFamily schema"
```

---

### Task 10: Family-scoped `GpuSessionRepository` + phantom-hours fix

**Files:**
- Modify: `chat-api/app/repositories/gpu.py`
- Test: `chat-api/tests/unit/repositories/test_gpu_repository.py`

**Interfaces:**
- Produces: `GpuSessionRepository(db, family: str = "transcription")`; `create(...)` stamps `family`; `close_open_sessions`, `extend_warm`, `warm_count_for_user_since` filter `family == self.family`; `hours_between`, `sessions_since` unfiltered. `hours_between` span starts at `coalesce(started_processing_at, started_at)` and excludes `instance_id IS NULL`.

- [ ] **Step 1: Failing tests** — add to `test_gpu_repository.py` (keep the existing ones; change `make_repo` to accept `family="transcription"` and pass it through):

```python
def compiled(db):
    stmt = db.execute.await_args.args[0]
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


async def test_close_open_sessions_is_family_scoped():
    repo, db = make_repo(rowcount=0, family="photogrammetry")
    await repo.close_open_sessions(NOW)
    assert "family = 'photogrammetry'" in compiled(db)


async def test_extend_warm_is_family_scoped():
    repo, db = make_repo(family="transcription")
    await repo.extend_warm(NOW)
    assert "family = 'transcription'" in compiled(db)


async def test_warm_count_is_family_scoped():
    repo, db = make_repo(family="transcription")
    await repo.warm_count_for_user_since("u", SINCE)
    assert "family = 'transcription'" in compiled(db)


async def test_hours_between_sums_all_families_and_ignores_rows_without_instance():
    repo, db = make_repo(scalar=0, family="photogrammetry")
    await repo.hours_between(SINCE, NOW, max_session_seconds=10800)
    sql = compiled(db)
    assert "family" not in sql
    assert "instance_id IS NOT NULL" in sql
    assert "coalesce(gpu_sessions.started_processing_at, gpu_sessions.started_at)" in sql


async def test_sessions_since_is_not_family_scoped():
    repo, db = make_repo(family="photogrammetry")
    db.execute.return_value.scalars.return_value.all.return_value = []
    await repo.sessions_since(SINCE)
    assert "family" not in compiled(db)


async def test_create_stamps_family():
    repo, db = make_repo(family="photogrammetry")
    db.add = MagicMock(); db.flush = AsyncMock()
    row = await repo.create(task_arn="arn", started_by="u", reason="job", warm_until=None)
    assert row.family == "photogrammetry"
```

Run: `uv run pytest tests/unit/repositories/test_gpu_repository.py -q` → new tests FAIL.

- [ ] **Step 2: Implement**

In `app/repositories/gpu.py`:

```python
class GpuSessionRepository:
    def __init__(self, db: AsyncSession, family: str = "transcription"):
        self.db = db
        self.family = family
```

`close_open_sessions`: add `GpuSession.family == self.family` to the `where`. `extend_warm`: same. `warm_count_for_user_since`: add `GpuSession.family == self.family`. `create`: `GpuSession(..., family=self.family)`.

`hours_between` — replace the span start and add the instance filter:

```python
        span_start = func.coalesce(GpuSession.started_processing_at, GpuSession.started_at)
        span_end = func.least(
            func.coalesce(GpuSession.ended_at, until),
            until,
            span_start + timedelta(seconds=max_session_seconds),
        )
        stmt = select(
            func.coalesce(func.sum(func.greatest(0, func.extract("epoch", span_end - func.greatest(span_start, since)))), 0)
        ).where(
            GpuSession.instance_id.is_not(None),
            span_start < until,
            func.coalesce(GpuSession.ended_at, until) > since,
        )
```

Update the docstring comment: "Rows that never got an instance (`instance_id IS NULL`) cost nothing and are excluded; a session's clock starts when the worker claimed it."

- [ ] **Step 3: Run**

Run: `cd chat-api && uv run pytest tests/unit -q` → all PASS (fix `test_hours_between_clamps_to_max_session_seconds` if its `make_interval` assertion now needs `coalesce(` — keep its intent).

- [ ] **Step 4: Commit**

```bash
git add chat-api/app/repositories/gpu.py chat-api/tests/unit/repositories/test_gpu_repository.py
git commit -m "feat(api): family-scoped gpu_sessions repository; phantom hours excluded from caps"
```

---

### Task 11: `GpuController(family=…)` with a per-family state cache; deps

**Files:**
- Modify: `chat-api/app/services/gpu_controller.py`, `chat-api/app/api/v1/gpu/deps.py`, `chat-api/app/api/v1/photogrammetry/deps.py`
- Test: `chat-api/tests/unit/services/test_gpu_controller.py`, `chat-api/tests/unit/api/test_gpu_deps.py`, `chat-api/tests/unit/api/test_photogrammetry_deps.py`

**Interfaces:**
- Produces: `GpuController(repo, launcher, settings, family: str = "transcription", cost_client=None, now=...)`; module `_state_cache: dict[str, tuple[float, list[str]]]`; `GpuSessionSummary(..., family=s.family)`.
- Produces: `gpu.deps.launcher_for(s, family: str) -> EcsWorkerLauncher` (task family = `s.gpu_worker_task_family` for `transcription`, `s.gpu_photogrammetry_task_family` for `photogrammetry`); `gpu.deps.build_controller(db, s, family) -> GpuController | None` (None when disabled or the family's task family is empty; the mock launcher when `use_mock_transcription`).

- [ ] **Step 1: Failing tests**

In `test_gpu_controller.py` change `make()` to `gc._state_cache.clear()` and add a `family="transcription"` kwarg passed to the constructor; add:

```python
async def test_state_cache_is_per_family():
    a, _, la = make(tasks=["RUNNING"], family="transcription")
    b, _, lb = make(tasks=[], family="photogrammetry")
    assert (await a.get_state()).worker_state == "running"
    assert (await b.get_state()).worker_state == "off"      # not served from a's cache
    assert la.list_worker_tasks.call_count == 1 and lb.list_worker_tasks.call_count == 1


async def test_ensure_worker_invalidates_only_its_family():
    a, _, la = make(tasks=["RUNNING"], family="transcription")
    b, _, _ = make(tasks=[], family="photogrammetry")
    await a.get_state(); await b.get_state()
    await b.ensure_worker("job", "u")
    await a.get_state()
    assert la.list_worker_tasks.call_count == 1           # a's cache survived b's launch


async def test_usage_summary_carries_family():
    ctl, repo, _ = make(family="photogrammetry")
    s = MagicMock(started_at=NOW, ended_at=None, reason="job", started_by="u", end_reason=None, family="photogrammetry")
    repo.sessions_since = AsyncMock(return_value=[s])
    usage = await ctl.usage("u")
    assert usage.sessions[0].family == "photogrammetry"
```

In `test_gpu_deps.py`, the two existing `_get_launcher` tests become `launcher_for(s, "transcription")` (same assertions); add `gpu_photogrammetry_task_family="photogrammetry-prod-worker"` to `make_settings` defaults, and add:

```python
def test_build_controller_photogrammetry_uses_its_task_family():
    s = make_settings(gpu_photogrammetry_task_family="photogrammetry-prod-worker")
    with patch.object(deps, "EcsWorkerLauncher") as L, patch.object(deps, "_get_cost_client"):
        ctl = deps.build_controller(MagicMock(), s, "photogrammetry")
    assert ctl is not None and ctl._family == "photogrammetry"
    assert L.call_args.args[1] == "photogrammetry-prod-worker"


def test_build_controller_photogrammetry_none_when_family_empty():
    s = make_settings(gpu_photogrammetry_task_family="")
    assert deps.build_controller(MagicMock(), s, "photogrammetry") is None
```

In `test_photogrammetry_deps.py`, `test_real_service_with_task_family_builds_cached_launcher` now asserts the service's `_gpu._family == "photogrammetry"` and that `gpu_deps.launcher_for` was used (patch `app.api.v1.gpu.deps.EcsWorkerLauncher`).

- [ ] **Step 2: Implement**

`gpu_controller.py`:

```python
_state_cache: dict[str, tuple[float, list[str]]] = {}   # family -> (expiry_monotonic, task statuses)

class GpuController:
    def __init__(self, repo, launcher, settings, family: str = "transcription", cost_client=None,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        ...
        self._family = family
```

`get_state`: `cached = _state_cache.get(self._family)`; `if cached is None or mono >= cached[0]: ... _state_cache[self._family] = (...)`. `ensure_worker`: every `_state_cache = None` becomes `_state_cache.pop(self._family, None)`. `usage`: `GpuSessionSummary(..., family=s.family)`.

`gpu/deps.py`:

```python
def launcher_for(s, family: str) -> EcsWorkerLauncher:
    task_family = s.gpu_worker_task_family if family == "transcription" else s.gpu_photogrammetry_task_family
    key = (s.gpu_cluster, task_family, s.gpu_capacity_provider, s.aws_region)
    launcher = _launchers.get(key)
    if launcher is None:
        launcher = _launchers[key] = EcsWorkerLauncher(*key)
    return launcher


def build_controller(db, s, family: str) -> GpuController | None:
    if s.use_mock_transcription:
        return GpuController(GpuSessionRepository(db, family), _mock_launcher, s, family=family)
    if not s.gpu_controller_enabled:
        return None
    task_family = s.gpu_worker_task_family if family == "transcription" else s.gpu_photogrammetry_task_family
    if not task_family:
        return None
    return GpuController(GpuSessionRepository(db, family), launcher_for(s, family), s, family=family,
                         cost_client=_get_cost_client(s))


def get_gpu_controller(db: AsyncSession = Depends(get_db)) -> GpuController | None:
    return build_controller(db, get_settings(), "transcription")
```

Delete `_get_launcher`. `photogrammetry/deps.py`: delete its `_launchers`/`_get_launcher`; `gpu = gpu_deps.build_controller(db, s, "photogrammetry")` (only in the real branch; the mock branch is unchanged).

- [ ] **Step 3: Run**

Run: `cd chat-api && uv run pytest tests/unit -q` → all PASS.

- [ ] **Step 4: Commit**

```bash
git add chat-api
git commit -m "feat(api): GpuController keyed by family — per-family state cache, launcher_for/build_controller"
```

---

### Task 12: `?family=` on `/gpu/state` and `/gpu/warm`

**Files:**
- Modify: the file holding the `/gpu` routes (`chat-api/app/api/v1/gpu/` — the one that defines `router = APIRouter()`), `chat-api/app/api/v1/gpu/deps.py`
- Test: `chat-api/tests/unit/api/test_gpu.py`

**Interfaces:**
- Produces: `gpu.deps.get_gpu_controller_by_family(family: GpuFamily = Query("transcription"), db=Depends(get_db)) -> GpuController | None`, used by the three `/gpu/*` routes only. `get_gpu_controller` (no query param) stays as the transcribe service's dependency — putting the `Query` on it would surface `?family=` on every transcribe route. `/gpu/usage` accepts `family` and ignores it (hours are summed).

- [ ] **Step 1: Failing tests** — in `test_gpu.py`, the existing `client` fixture's override moves from `get_gpu_controller` to `get_gpu_controller_by_family` (import it from `app.api.v1.gpu.deps`); add a second fixture that patches `deps.build_controller` so the query param is exercised:

```python
@pytest.fixture
async def client_by_family():
    ctls = {}
    def build(db, s, family):
        ctl = ctls.setdefault(family, MagicMock())
        ctl.get_state = AsyncMock(return_value=GpuStateResponse(worker_state="off", estimated_wait_seconds=180))
        ctl.ensure_worker = AsyncMock(return_value=GpuStateResponse(worker_state="starting", estimated_wait_seconds=120))
        return ctl
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user1", "cognito:groups": []}
    with patch("app.api.v1.gpu.deps.build_controller", side_effect=build), patch("app.db.session.init_db", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, ctls
    app.dependency_overrides.clear()


async def test_state_defaults_to_transcription(client_by_family):
    ac, ctls = client_by_family
    r = await ac.get("/api/v1/gpu/state", headers=H)
    assert r.status_code == 200 and set(ctls) == {"transcription"}


async def test_state_family_photogrammetry(client_by_family):
    ac, ctls = client_by_family
    r = await ac.get("/api/v1/gpu/state?family=photogrammetry", headers=H)
    assert r.status_code == 200 and set(ctls) == {"photogrammetry"}


async def test_warm_family_photogrammetry(client_by_family):
    ac, ctls = client_by_family
    r = await ac.post("/api/v1/gpu/warm?family=photogrammetry", headers=H)
    assert r.status_code == 200
    ctls["photogrammetry"].ensure_worker.assert_awaited_once_with("warm", "user1", is_admin=False)


async def test_unknown_family_is_422(client_by_family):
    ac, _ = client_by_family
    assert (await ac.get("/api/v1/gpu/state?family=nope", headers=H)).status_code == 422
```

- [ ] **Step 2: Implement**

`gpu/deps.py`:

```python
from fastapi import Depends, Query
from app.schemas.gpu import GpuFamily

def get_gpu_controller_by_family(
    family: GpuFamily = Query("transcription"), db: AsyncSession = Depends(get_db)
) -> GpuController | None:
    return build_controller(db, get_settings(), family)
```

In the `/gpu` routes file replace `Depends(get_gpu_controller)` with `Depends(get_gpu_controller_by_family)` on `gpu_state`, `gpu_warm` and `gpu_usage`. `get_gpu_controller` (Task 11) is untouched and still serves `transcribe/deps.py`.

- [ ] **Step 3: Run**

Run: `cd chat-api && uv run pytest tests/unit -q` → all PASS.

- [ ] **Step 4: Commit**

```bash
git add chat-api
git commit -m "feat(api): ?family= on /gpu/state and /gpu/warm"
```

---

### Task 13: Publish the job on confirm; queue-URL setting

**Files:**
- Modify: `chat-api/app/services/sqs_publisher.py`, `chat-api/app/config.py`, `chat-api/.env.example`, `chat-api/app/services/photogrammetry_service.py`, `chat-api/app/api/v1/photogrammetry/deps.py`
- Test: `chat-api/tests/unit/services/test_photogrammetry_service.py`, `chat-api/tests/unit/api/test_photogrammetry_deps.py`, `chat-api/tests/unit/services/test_sqs_publisher.py` (create)

**Interfaces:**
- Produces: `SQSPublisher.publish_photogrammetry_job(job_id: UUID) -> None` (body `{"type": "photogrammetry_job", "job_id": str}`), `MockSQSPublisher.publish_photogrammetry_job`; `Settings.photogrammetry_sqs_queue_url: str = ""`; `PhotogrammetryService(repo, storage, settings, gpu=None, sqs=None)` — `_queue` publishes after the first commit; `deps` passes `gpu` only when **both** `gpu_photogrammetry_task_family` and `photogrammetry_sqs_queue_url` are set, and `sqs=SQSPublisher(s.photogrammetry_sqs_queue_url, s.aws_region)` in that case.

- [ ] **Step 1: Failing tests**

`tests/unit/services/test_sqs_publisher.py`:

```python
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.sqs_publisher import MockSQSPublisher, SQSPublisher


def test_publish_photogrammetry_job_body():
    with patch("boto3.client") as client:
        pub = SQSPublisher("https://sqs.test/q", "us-east-1")
        job_id = uuid4()
        pub.publish_photogrammetry_job(job_id)
    kw = client.return_value.send_message.call_args.kwargs
    assert kw["QueueUrl"] == "https://sqs.test/q"
    assert json.loads(kw["MessageBody"]) == {"type": "photogrammetry_job", "job_id": str(job_id)}


def test_mock_has_the_method():
    MockSQSPublisher().publish_photogrammetry_job(uuid4())
```

In `test_photogrammetry_service.py`, extend `make_service` with `sqs=None` → `PhotogrammetryService(repo, storage, settings, gpu, sqs)` and add:

```python
async def test_confirm_publishes_after_commit_then_ensures_worker():
    order = []
    gpu = MagicMock(); gpu.ensure_worker = AsyncMock(side_effect=lambda *a, **k: order.append("ensure"))
    sqs = MagicMock(); sqs.publish_photogrammetry_job = MagicMock(side_effect=lambda job_id: order.append("publish"))
    job = make_job(status="pending", image_count=6)
    svc, repo, storage = make_service(gpu=gpu, job=job, keys=[f"k{i}" for i in range(6)], sqs=sqs)
    repo.db.commit = AsyncMock(side_effect=lambda: order.append("commit"))
    await svc.confirm_job("user1", job.id)
    assert order[:3] == ["commit", "publish", "ensure"]
    sqs.publish_photogrammetry_job.assert_called_once_with(job.id)


async def test_sample_job_publishes():
    gpu = MagicMock(); gpu.ensure_worker = AsyncMock()
    sqs = MagicMock()
    svc, repo, storage = make_service(gpu=gpu, keys=["samples/photogrammetry/images/0001.jpg"] * 8, sqs=sqs)
    r = await svc.create_sample_job("user1")
    sqs.publish_photogrammetry_job.assert_called_once_with(r.job_id)
```

(`make_service` returns whatever tuple it returns today — adapt the unpacking to the file's shape.)

In `test_photogrammetry_deps.py`:

```python
def test_real_service_without_queue_url_has_no_gpu():
    s = make_settings(photogrammetry_sqs_queue_url="")
    with patch.object(deps, "get_settings", return_value=s), patch.object(deps, "AudioStorageService"):
        svc = deps.get_photogrammetry_service(db=MagicMock())
    assert svc._gpu is None


def test_real_service_with_family_and_queue_builds_publisher():
    s = make_settings(photogrammetry_sqs_queue_url="https://sqs.test/pg")
    with patch.object(deps, "get_settings", return_value=s), patch.object(deps, "AudioStorageService"), \
         patch.object(deps, "SQSPublisher") as P, patch("app.api.v1.gpu.deps.EcsWorkerLauncher"), \
         patch("app.api.v1.gpu.deps._get_cost_client"):
        svc = deps.get_photogrammetry_service(db=MagicMock())
    assert svc._gpu is not None
    P.assert_called_once_with("https://sqs.test/pg", "us-east-1")
```

Add `photogrammetry_sqs_queue_url="https://sqs.test/pg"` to `make_settings` defaults in that file.

- [ ] **Step 2: Implement**

`sqs_publisher.py` — both classes:

```python
    def publish_photogrammetry_job(self, job_id: UUID) -> None:
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps({"type": "photogrammetry_job", "job_id": str(job_id)}),
        )
```
(`MockSQSPublisher`: `pass`.)

`config.py` under the photogrammetry block: `photogrammetry_sqs_queue_url: str = ""   # worker queue; empty = not deployed (confirm returns 503)`. `.env.example`: `PHOTOGRAMMETRY_SQS_QUEUE_URL=`.

`photogrammetry_service.py`:

```python
    def __init__(self, repo, storage, settings, gpu=None, sqs=None):
        ...
        self._sqs = sqs

    async def _queue(self, job_id: UUID, user_id: str) -> None:
        await self._repo.update_job_status(job_id, "queued")
        await self._repo.db.commit()
        if self._sqs is not None:
            self._sqs.publish_photogrammetry_job(job_id)   # after the commit so the worker finds the row
        try:
            await self._gpu.ensure_worker("job", user_id)
        except GpuCapExceeded:
            pass
        await self._repo.db.commit()
```

`LocalPhotogrammetryService` passes `sqs=None` (mock walk, no queue). `deps.py`:

```python
    gpu = sqs = None
    if s.gpu_controller_enabled and s.gpu_photogrammetry_task_family and s.photogrammetry_sqs_queue_url:
        gpu = gpu_deps.build_controller(db, s, "photogrammetry")
        sqs = SQSPublisher(s.photogrammetry_sqs_queue_url, s.aws_region)
    return PhotogrammetryService(repo, AudioStorageService(s), s, gpu, sqs)
```

- [ ] **Step 3: Run**

Run: `cd chat-api && uv run pytest tests/unit -q` → all PASS.

- [ ] **Step 4: Commit**

```bash
git add chat-api
git commit -m "feat(api): publish photogrammetry_job on confirm; PHOTOGRAMMETRY_SQS_QUEUE_URL gates deployment with the task family"
```

---

# Part D — `chat-vue`

### Task 14: `GpuStatusBar` per family; Scan page hides *Warm*

**Files:**
- Modify: `chat-vue/src/lib/gpuApi.ts`, `chat-vue/src/stores/gpu.ts`, `chat-vue/src/components/transcribe/GpuStatusBar.vue`, `chat-vue/src/views/PhotogrammetryView.vue`, `chat-vue/src/types/index.ts` (or wherever `GpuUsage` is declared — `grep -rn "GpuUsage" src/types`), `chat-vue/src/mocks/handlers.ts`

**Interfaces:**
- Consumes: `GET /api/v1/gpu/state?family=`, `POST /api/v1/gpu/warm?family=`, `GpuUsage.sessions[].family`.
- Produces: `GpuFamily = "transcription" | "photogrammetry"`; `getGpuState(family)`, `warmGpu(family)`; store `startPolling(family)`, `warm()` uses the stored family; `GpuStatusBar` prop `family` (default `"transcription"`), `showWarm` computed = `family === "transcription"`.

- [ ] **Step 1: Types and API**

In the types file: `export type GpuFamily = "transcription" | "photogrammetry"` and add `family: GpuFamily` to the session element type of `GpuUsage.sessions`.

`gpuApi.ts`:

```ts
import type { GpuFamily, GpuState, GpuUsage } from "@/types"

export async function getGpuState(family: GpuFamily = "transcription"): Promise<GpuState> {
  return (await apiClient.get("/api/v1/gpu/state", { params: { family } })).data
}
export async function warmGpu(family: GpuFamily = "transcription"): Promise<GpuState> {
  return (await apiClient.post("/api/v1/gpu/warm", null, { params: { family } })).data
}
```

- [ ] **Step 2: Store**

In `stores/gpu.ts`: `const family = ref<GpuFamily>("transcription")`; `refreshState` → `api.getGpuState(family.value)`; `warm` → `api.warmGpu(family.value)`; `startPolling(f: GpuFamily = "transcription")` sets `family.value = f; state.value = null` before the first tick (so a page switch never shows the other worker's last state); export `family`.

- [ ] **Step 3: Component and view**

`GpuStatusBar.vue`:

```ts
const props = withDefaults(defineProps<{ family?: GpuFamily }>(), { family: "transcription" })
const showWarm = computed(() => props.family === "transcription")
onMounted(() => { gpu.startPolling(props.family); ... })
```

Wrap the warm `<button>` in `v-if="showWarm"`. `PhotogrammetryView.vue`: `<GpuStatusBar family="photogrammetry" />`. In `mocks/handlers.ts` nothing changes (the handlers match `*/api/v1/gpu/state` regardless of query).

- [ ] **Step 4: Verify**

Run: `cd chat-vue && npm run type-check && npm run build`
Expected: both clean. Then `npm run dev` with `VITE_DEV_AUTH_BYPASS=true` against the API in mock mode (`USE_MOCK_TRANSCRIPTION=true USE_MOCK_PHOTOGRAMMETRY=true`): `/transcribe` shows the *Warm it up* button, `/photogrammetry` shows the bar without it; the network tab shows `family=photogrammetry` on the Scan page's `/gpu/state` calls.

- [ ] **Step 5: Commit**

```bash
git add chat-vue
git commit -m "feat(vue): GpuStatusBar per family; Scan page polls the photogrammetry worker and hides Warm"
```

---

# Part E — infrastructure and tooling

### Task 15: Terraform — `modules/photogrammetry`, lifecycle rule, API env locals

**Files:**
- Create: `infra/modules/photogrammetry/main.tf`, `infra/modules/photogrammetry/variables.tf`, `infra/modules/photogrammetry/outputs.tf`
- Modify: `infra/modules/transcription/main.tf` (lifecycle rule), `infra/environments/transcription-prod/main.tf`, `infra/environments/transcription-prod/variables.tf`, `infra/environments/prod/main.tf`

**Interfaces:**
- Produces: module inputs `environment`, `aws_region`, `audio_bucket_name`, `audio_bucket_arn`, `database_url_secret_arn`, `github_org` (default `peaslee-org`), `github_repo`, `image_tag` (default `latest`), `idle_exit_seconds` (900), `max_lifetime_seconds` (10800), `job_timeout_seconds` (3600), `worker_cpu` (3072), `worker_memory` (14000); outputs `queue_url`, `dlq_url`, `worker_ecr_url`, `worker_github_actions_role_arn`, `worker_task_family`.
- Produces: prod locals `photogrammetry_task_family = "photogrammetry-${var.environment}-worker"` and env `GPU_PHOTOGRAMMETRY_TASK_FAMILY`, `PHOTOGRAMMETRY_SQS_QUEUE_URL` (from a new `var.photogrammetry_sqs_queue_url`, default `""`).

- [ ] **Step 1: `variables.tf`**

```hcl
variable "environment" {
  type = string
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "audio_bucket_name" {
  type        = string
  description = "The transcription module's audio bucket; photogrammetry/ and samples/photogrammetry/ live in it."
}

variable "audio_bucket_arn" {
  type = string
}

variable "database_url_secret_arn" {
  type        = string
  description = "Secrets Manager secret holding DATABASE_URL; injected by ECS, never read by Terraform."
}

variable "github_org" {
  type    = string
  default = "peaslee-org"
}

variable "github_repo" {
  type = string
}

variable "image_tag" {
  type        = string
  description = "Image tag the task definition points at. CI registers new revisions outside Terraform; set this to the deployed tag so plan stays clean."
  default     = "latest"
}

variable "idle_exit_seconds" {
  type        = number
  description = "Must equal prod's gpu_idle_exit_seconds (same rule as the transcription worker)."
  default     = 900
}

variable "max_lifetime_seconds" {
  type        = number
  description = "Must equal prod's gpu_max_lifetime_seconds."
  default     = 10800
}

variable "job_timeout_seconds" {
  type        = number
  description = "Per-job wall clock; the worker kills the current tool and fails the job past this."
  default     = 3600
}

variable "worker_cpu" {
  type    = number
  default = 3072
}

variable "worker_memory" {
  type        = number
  description = "g4dn.xlarge has 16 GiB; dense reconstruction is RAM-bound. 14000 leaves room for the agent and pins one task per instance."
  default     = 14000
}
```

- [ ] **Step 2: `main.tf`**

```hcl
locals {
  name = "photogrammetry-${var.environment}"
}

data "aws_caller_identity" "current" {}
data "aws_iam_openid_connect_provider" "github" { url = "https://token.actions.githubusercontent.com" }
data "aws_iam_role" "api_task" { name = "chat-api-${var.environment}-task" }
data "aws_sns_topic" "gpu_alerts" { name = "gpu-${var.environment}-alerts" }

# ── SQS ───────────────────────────────────────────────────────────────────────
resource "aws_sqs_queue" "dlq" {
  name                      = "${local.name}-dlq"
  message_retention_seconds = 1209600
  tags                      = { Environment = var.environment, CostCenter = "gpu" }
}

resource "aws_sqs_queue" "main" {
  name                       = local.name
  visibility_timeout_seconds = 600
  message_retention_seconds  = 345600
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.dlq.arn, maxReceiveCount = 3 })
  tags                       = { Environment = var.environment, CostCenter = "gpu" }
}

# ── ECR ───────────────────────────────────────────────────────────────────────
resource "aws_ecr_repository" "worker" {
  name                 = "${local.name}-worker"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }
  tags = { Environment = var.environment, CostCenter = "gpu" }
}

resource "aws_ecr_lifecycle_policy" "worker" {
  repository = aws_ecr_repository.worker.name
  policy = jsonencode({ rules = [{
    rulePriority = 1, description = "Keep last 2 images",
    selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 2 },
    action       = { type = "expire" }
  }] })
}

# ── IAM: execution + task roles ───────────────────────────────────────────────
resource "aws_iam_role" "worker_execution" {
  name = "${local.name}-worker-execution"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy_attachment" "worker_execution" {
  role       = aws_iam_role.worker_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "worker_execution_secrets" {
  name = "db-secret"
  role = aws_iam_role.worker_execution.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Action = "secretsmanager:GetSecretValue", Resource = var.database_url_secret_arn }] })
}

resource "aws_iam_role" "worker_task" {
  name = "${local.name}-worker-task"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy" "worker_task" {
  name = "worker-permissions"
  role = aws_iam_role.worker_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"],
        Resource = ["${var.audio_bucket_arn}/photogrammetry/*", "${var.audio_bucket_arn}/samples/photogrammetry/*"] },
      { Effect = "Allow", Action = "s3:ListBucket", Resource = var.audio_bucket_arn,
        Condition = { StringLike = { "s3:prefix" = ["photogrammetry/*", "samples/photogrammetry/*"] } } },
      { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"],
        Resource = aws_sqs_queue.main.arn },
    ]
  })
}

# ── IAM: GitHub Actions deploy role ───────────────────────────────────────────
resource "aws_iam_role" "worker_github_actions" {
  name = "${local.name}-worker-github-actions"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn },
    Action = "sts:AssumeRoleWithWebIdentity",
    Condition = {
      StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
      StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/main" }
    } }] })
}

resource "aws_iam_role_policy" "worker_github_actions" {
  name = "worker-github-actions-deploy"
  role = aws_iam_role.worker_github_actions.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "ECRAuth", Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" },
      { Sid = "ECRPush", Effect = "Allow", Resource = aws_ecr_repository.worker.arn,
        Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage",
                  "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"] },
      { Sid = "ECSRead", Effect = "Allow", Action = ["ecs:DescribeTaskDefinition"], Resource = "*" },
      { Sid = "ECSDeploy", Effect = "Allow", Action = ["ecs:RegisterTaskDefinition", "ecs:TagResource"], Resource = "*" },
      { Sid = "IAMPassRole", Effect = "Allow", Action = "iam:PassRole",
        Resource = [aws_iam_role.worker_execution.arn, aws_iam_role.worker_task.arn] },
    ]
  })
}

# ── IAM: let the API RunTask this family ──────────────────────────────────────
resource "aws_iam_role_policy" "api_photogrammetry" {
  name = "photogrammetry"
  role = data.aws_iam_role.api_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "GpuRunWorker", Effect = "Allow", Action = "ecs:RunTask",
        Resource = "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task-definition/${local.name}-worker:*" },
      { Sid = "GpuPassWorkerRoles", Effect = "Allow", Action = "iam:PassRole",
        Resource = [aws_iam_role.worker_execution.arn, aws_iam_role.worker_task.arn] },
      { Sid = "PublishJobs", Effect = "Allow", Action = "sqs:SendMessage", Resource = aws_sqs_queue.main.arn },
    ]
  })
}

# ── Logs, alarm ───────────────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${local.name}-worker"
  retention_in_days = 30
  tags              = { Environment = var.environment, CostCenter = "gpu" }
}

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "${local.name}-dlq-not-empty"
  alarm_description   = "A photogrammetry job message landed in the DLQ after exhausting retries."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.gpu_alerts.arn]
  ok_actions          = [data.aws_sns_topic.gpu_alerts.arn]
  tags                = { Environment = var.environment, CostCenter = "gpu" }
}

# ── ECS task definition (no service; the API RunTasks it onto gpu-<env>) ─────
resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  network_mode             = "bridge"
  requires_compatibilities = ["EC2"]
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.worker_execution.arn
  task_role_arn            = aws_iam_role.worker_task.arn

  container_definitions = jsonencode([{
    name      = "photogrammetry-worker"
    image     = "${aws_ecr_repository.worker.repository_url}:${var.image_tag}"
    essential = true
    resourceRequirements = [{ type = "GPU", value = "1" }]
    environment = [
      { name = "AUDIO_BUCKET_NAME", value = var.audio_bucket_name },
      { name = "PHOTOGRAMMETRY_SQS_QUEUE_URL", value = aws_sqs_queue.main.url },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "IDLE_EXIT_SECONDS", value = tostring(var.idle_exit_seconds) },
      { name = "MAX_LIFETIME_SECONDS", value = tostring(var.max_lifetime_seconds) },
      { name = "PHOTOGRAMMETRY_JOB_TIMEOUT_SECONDS", value = tostring(var.job_timeout_seconds) },
    ]
    secrets = [{ name = "DATABASE_URL", valueFrom = var.database_url_secret_arn }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.worker.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])

  tags = { Environment = var.environment, CostCenter = "gpu" }
}
```

`outputs.tf`: `queue_url`, `dlq_url`, `worker_ecr_url`, `worker_github_actions_role_arn`, `worker_task_family` (from the resources above, with descriptions).

- [ ] **Step 3: Wire the environments**

`modules/transcription/main.tf` — in `aws_s3_bucket_lifecycle_configuration.audio` add a second rule:

```hcl
  rule {
    id     = "expire-photogrammetry-objects"
    status = "Enabled"
    filter { prefix = "photogrammetry/" }
    expiration { days = 30 }
  }
```

`environments/transcription-prod/main.tf`:

```hcl
module "photogrammetry" {
  source                  = "../../modules/photogrammetry"
  environment             = var.environment
  aws_region              = var.aws_region
  audio_bucket_name       = module.transcription.bucket_name
  audio_bucket_arn        = "arn:aws:s3:::${module.transcription.bucket_name}"
  database_url_secret_arn = var.database_url_secret_arn
  github_repo             = "chat"
  image_tag               = var.photogrammetry_image_tag
  idle_exit_seconds       = var.idle_exit_seconds
  max_lifetime_seconds    = var.max_lifetime_seconds
}

output "photogrammetry_queue_url" { value = module.photogrammetry.queue_url }
output "photogrammetry_worker_ecr_url" { value = module.photogrammetry.worker_ecr_url }
output "photogrammetry_github_actions_role_arn" { value = module.photogrammetry.worker_github_actions_role_arn }
```

`environments/transcription-prod/variables.tf`: `variable "photogrammetry_image_tag" { type = string, default = "latest", description = "…same contract as image_tag, for the photogrammetry worker…" }`.

`environments/prod/main.tf`: local `photogrammetry_task_family = "photogrammetry-${var.environment}-worker"`; variable `photogrammetry_sqs_queue_url` (string, default `""`, description "Photogrammetry worker queue URL from the transcription-prod state; empty keeps the feature off (confirm returns 503)"); append to `extra_environment`:

```hcl
    { name = "GPU_PHOTOGRAMMETRY_TASK_FAMILY", value = var.photogrammetry_sqs_queue_url == "" ? "" : local.photogrammetry_task_family },
    { name = "PHOTOGRAMMETRY_SQS_QUEUE_URL", value = var.photogrammetry_sqs_queue_url },
```

(One tfvars value flips both; empty = off — the cutover switch from spec §4.)

- [ ] **Step 4: Validate**

Run:

```bash
cd infra && terraform fmt -recursive -check
for e in transcription-prod prod; do (cd environments/$e && terraform init -backend=false -input=false >/dev/null && terraform validate); done
```

Expected: `fmt` silent; both `Success! The configuration is valid.` (`tf-validate.yml` runs the same in CI.) Do **not** run `plan` — the real tfvars live in cm/aws `overlay/`; plans are a runbook step.

- [ ] **Step 5: Commit**

```bash
git add infra
git commit -m "infra: photogrammetry module (queue, ECR, task family, roles, DLQ alarm), bucket lifecycle rule, API env switch"
```

---

### Task 16: Multi-image AMI bake, TODO cleanup, docs

**Files:**
- Modify: `scripts/deploy/build-gpu-ami.sh`, `docs/TODO.md`, `docs/design/photogrammetry-worker-spec.md` (Status line), `CLAUDE.md` (root, if it lists the workers)

- [ ] **Step 1: `build-gpu-ami.sh` takes a comma-separated image list**

Change the header comment's usage to `<base-ami> <image-uri:tag>[,<image-uri:tag>…] <subnet-id> <sg-id> <instance-profile> [env]` and:

```bash
IMAGES=$2; IFS=',' read -r -a IMAGE_LIST <<< "$IMAGES"; IMAGE=${IMAGE_LIST[0]}
```

keep `TAG`/`NAME`/`REGISTRY` derived from `$IMAGE` (the first), and in `USERDATA` replace the single `docker pull ${IMAGE}` with:

```bash
for IMG in ${IMAGE_LIST[*]}; do docker pull \$IMG; done
```

(Inside the heredoc the loop expands `${IMAGE_LIST[*]}` at script time and `\$IMG` at instance time.) Registry login stays once — both repos are in the same account registry. The `Image` tag value becomes `${IMAGES//\//_}` (both URIs, `/` → `_`).

Verify: `bash -n scripts/deploy/build-gpu-ami.sh` and a dry echo of the user-data: temporarily `echo "$USERDATA"; exit 0` after it is built, run with dummy args, confirm two `docker pull` lines, remove the echo.

- [ ] **Step 2: `docs/TODO.md`**

Remove the five items marked `→ worker spec …` (they are implemented by this plan). Add under **Infra**: "Photogrammetry: `gpu_max_size` 2 is exactly the account's current On-Demand G/VT quota; a third family needs a quota increase." Under **Worker image**: "Headless mesh-render `preview.png` (pyrender + EGL) — replaces the first-photo preview (worker spec decision 4)."

- [ ] **Step 3: Spec status**

`docs/design/photogrammetry-worker-spec.md` line 3: `**Status:** implemented on branch photogrammetry-worker (plan docs/superpowers/plans/2026-08-27-photogrammetry-worker.md); cutover per §4 pending`.

- [ ] **Step 4: Commit**

```bash
git add scripts/deploy/build-gpu-ami.sh docs/TODO.md docs/design/photogrammetry-worker-spec.md
git commit -m "docs: AMI bake pulls both worker images; TODO items absorbed by the worker spec; spec status"
```

---

## After the plan (not tasks — Neil-side, private track)

- **cm/aws runbook** `2026-08-xx-photogrammetry-go-live-runbook.md` with the five cutover steps from spec §4 and real IDs; `overlay/chat/terraform.tfvars` gains `photogrammetry_sqs_queue_url` and `photogrammetry_image_tag`; GitHub secret `AWS_DEPLOY_ROLE_ARN_PHOTOGRAMMETRY` from the new module's output; sample photos uploaded once to `samples/photogrammetry/images/` in the audio bucket.
- Acceptance per spec §5 (≈ 1 GPU-hour).
