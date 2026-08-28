# Photogrammetry worker — design spec

**Date:** 2026-08-27 · **Status:** live in prod 2026-08-28 (go-live runbook executed; acceptance §5 all passed; two pipeline fixes found by the CPU smoke and one by acceptance — see the cm/aws runbook)
docs/superpowers/plans/2026-08-27-photogrammetry-worker.md); cutover per §4 pending · **Implements:**
the contract in `photogrammetry-ui-spec.md` §1 and the constraints in its §7

## Goal

Ship the real reconstruction worker behind the photogrammetry UI: an ECS task on the shared
`gpu-<env>` capacity provider that takes a confirmed job's photos from S3, runs COLMAP → OpenMVS →
texturing on the GPU, and writes `mesh.glb` + `preview.png` back — walking the row through
`processing/sfm → dense → mesh → texture → complete` exactly as the mock does. The API stops
returning 503 on `confirm` once `GPU_PHOTOGRAMMETRY_TASK_FAMILY` is set.

Along the way this spec pays the debt the UI spec deferred: `GpuController` and the
`gpu_sessions` ledger become safe for two task families, the transcription worker's lifecycle
code moves into a shared package, and the queued phantom-hours and status-bar items are closed.

Decisions from the brainstorm:

| # | Question | Decision |
|---|---|---|
| 1 | How the worker finds work | **SQS queue, like transcribe** (`photogrammetry-<env>`). Visibility extension, spot-interruption release and retry come from the existing machinery. |
| 2 | Reconstruction toolchain | **COLMAP + OpenMVS**, real photo texture atlas. COLMAP-only (vertex colours) rejected as too low-fidelity for small objects. |
| 3 | Where the code lives | **Shared package `gpu-worker/`** + thin `photogrammetry-worker/`; the transcription worker becomes a consumer. Copying the lifecycle files rejected. |
| 4 | `preview.png` | **First input photo, downscaled to 640 px.** A headless mesh render is a later add. |
| 5 | Ledger | `gpu_sessions.family` column; **caps remain summed across families** — one pool, one budget. |

## 1. Worker pipeline and data flow

### Trigger

`PhotogrammetryService.confirm_job` and `create_sample_job` already set `queued` and call
`ensure_worker("job", user)`. They additionally publish, **after the commit** (the ordering rule
transcribe learned for sample embeddings):

```json
{"type": "photogrammetry_job", "job_id": "<uuid>"}
```

via `SQSPublisher.publish_photogrammetry_job(job_id)` to `settings.photogrammetry_sqs_queue_url`
(new API setting `PHOTOGRAMMETRY_SQS_QUEUE_URL`, default `""`; empty is treated like an empty task
family — `WorkerNotDeployed`, 503).
Sample jobs take the same path; their `input_prefix` is `settings.photogrammetry_sample_prefix +
"images/"` and their outputs still go under the job's own `output/` prefix (§7 of the UI spec).

### Worker process

`photogrammetry-worker/main.py` is transcribe's shape with the transcription parts removed:

```python
HANDLERS = {"photogrammetry_job": process_photogrammetry_job}
run_sqs_worker(queue_url=settings.PHOTOGRAMMETRY_SQS_QUEUE_URL, handlers=HANDLERS, ...)
```

`run_sqs_worker` (shared package, §2) long-polls one message at a time, extends visibility on a
thread, runs a `SpotWatcher` that releases the in-flight message on an interruption notice, and
drives `WorkerLoop` for idle exit, max lifetime and the `gpu_sessions` claim/heartbeat/close.

### Handler — `process_photogrammetry_job(body, settings)`

Runs in a scratch directory `/tmp/pg/<job_id>` on the instance's 80 GB root, removed in `finally`.

| Step | Row `stage` | Command(s) | Rule |
|---|---|---|---|
| load | — | load the row (plain `get`; concurrent delivery is prevented by the SQS visibility timeout, extended while the job runs); if status ∉ {`queued`, `processing`} → ack and return | idempotent on redelivery |
| fetch | `sfm` (status → `processing`) | list `input_prefix`; download; fail if fewer than `image_count` objects | |
| SfM | `sfm` | `colmap feature_extractor` (SIFT, GPU) → `colmap exhaustive_matcher` → `colmap mapper` | take the model with the most registered images; **fail if registered < 60 % of `image_count`** ("Only N of M photos could be matched — add overlap and try again") |
| dense | `dense` | `colmap image_undistorter` → `InterfaceCOLMAP` → `DensifyPointCloud --resolution-level 2` | resolution level fixed for the 16 GB T4 |
| mesh | `mesh` | `ReconstructMesh` → `RefineMesh` | **`RefineMesh` skipped when `image_count` > 100** (time cap) |
| texture | `texture` | `TextureMesh` → `mesh_textured.obj` + atlas PNG → `trimesh.load(...).export("mesh.glb")` | GLB via trimesh (pure Python, no EGL); `preview.png` = `input/0001.*` resized to 640 px on the long edge |
| publish | — | upload `output/mesh.glb`, `output/preview.png`; row → `complete`, `mesh_s3_key`, `preview_s3_key`, `completed_at`; ack | |

Each stage is a subprocess with stdout/stderr captured to the task log. `stage` is written to the
row at the start of each step; the UI's poll shows it within 30 s.

### Failure handling

| Event | Row | Message | Rationale |
|---|---|---|---|
| Any exception in a stage | `failed`, `error_message` = the rule's text, else the first line of the tool's stderr (≤ 1 000 chars) | **acked** | a deterministic failure must not retry three times on a $0.53/h box |
| `PHOTOGRAMMETRY_JOB_TIMEOUT_SECONDS` elapsed (default 3 600) | `failed`, "Reconstruction exceeded 60 minutes" | acked | current subprocess is killed |
| Spot interruption notice | reset to `queued`, `stage = NULL` | **released** (SpotWatcher, existing) | `pipeline/runner.py` polls `SpotWatcher.interrupted` every 5 s while a subprocess runs; when set it kills the subprocess and raises `Interrupted`, which the handler turns into the row reset and `run_sqs_worker` treats as "do not ack". Next worker restarts from scratch |
| Worker dies mid-job (OOM, crash) | stays `processing` | redelivered after visibility timeout (≤ 3 times, then DLQ) | the load step accepts `processing` and restarts; DLQ = manual look |

The SQS DLQ is the only place a job can be "lost"; a CloudWatch alarm on its depth is part of §4.

## 2. Repository layout and the shared package

### `gpu-worker/` (new, repo root) — package `gpu_worker`

Pure Python: `boto3`, `sqlalchemy`, `psycopg2-binary`. No torch, no ML. Installed into both worker
images with `pip install ./gpu-worker`.

| Module | Source | Change |
|---|---|---|
| `gpu_worker/loop.py` | `transcription-worker/worker_loop.py` | none |
| `gpu_worker/spot_watcher.py`, `gpu_worker/ecs_metadata.py` | `services/…` | none |
| `gpu_worker/session.py` | `services/gpu_session.py` | `GpuSessionStore(task_arn, instance_id, session_factory)` — the factory is **required**; no import of a worker-local `db` |
| `gpu_worker/db.py` | new | `make_session_factory(database_url)` (the asyncpg → psycopg2 normalisation from `db.py`) and a minimal `GpuSession` model on the package's own `Base` — only the columns the store touches (`task_arn`, `instance_id`, `started_processing_at`, `last_seen_at`, `warm_until`, `ended_at`, `end_reason`) |
| `gpu_worker/sqs.py` | extracted from `transcription-worker/main.py` | `run_sqs_worker(queue_url, handlers, settings)`: receive, visibility extender, per-message SpotWatcher, idle watcher, delete-on-success, `WorkerLoop` wiring |
| `gpu_worker/tests/` | `test_spot_watcher.py` moves; loop tests added (idle, max lifetime, warm extension, interrupt) | |

`transcription-worker/main.py` shrinks to the torch/huggingface patches, `HANDLERS`, and one
`run_sqs_worker(...)` call. `transcription-worker/models.py` drops its `GpuSession` copy;
`db.py` stays for the transcription tables.

### `photogrammetry-worker/` (new)

| File | Content |
|---|---|
| `main.py` | ≈ 15 lines: settings, `HANDLERS`, `run_sqs_worker` |
| `config.py` | `Settings`: `DATABASE_URL`, `AUDIO_BUCKET_NAME`, `PHOTOGRAMMETRY_SQS_QUEUE_URL`, `AWS_REGION` (`us-east-1`), `IDLE_EXIT_SECONDS` (900), `MAX_LIFETIME_SECONDS` (10 800), `PHOTOGRAMMETRY_JOB_TIMEOUT_SECONDS` (3 600), `SQS_VISIBILITY_TIMEOUT` (600), `SQS_VISIBILITY_EXTENSION_INTERVAL` (300), `WORK_DIR` (`/tmp/pg`), `COLMAP_USE_GPU` (`1`) |
| `models.py` | `PhotogrammetryJob` only (mirrors the API model) |
| `handlers/photogrammetry.py` | the stage table above; reads as a sequence of `pipeline.*` calls |
| `pipeline/colmap.py`, `pipeline/openmvs.py`, `pipeline/export.py` | thin subprocess wrappers returning paths; `export.py` = trimesh GLB + Pillow preview |
| `pipeline/runner.py` | `run(cmd, timeout_remaining)` — captures output, enforces the job deadline, raises `StageError(tool, first_stderr_line)` |
| `tests/` | §5 |
| `Dockerfile`, `pyproject.toml`, `CLAUDE.md` | |

`COLMAP_USE_GPU=0` makes the same pipeline run on a CPU-only box (fitlet) — slow, but it proves
the container end-to-end before an AMI bake.

### Container

Multi-stage `photogrammetry-worker/Dockerfile`, build context = **repo root**
(`docker build -f photogrammetry-worker/Dockerfile .`) so `COPY gpu-worker/` works:

1. `FROM nvidia/cuda:12.9.1-devel-ubuntu24.04` — the COLMAP image's own Ubuntu/CUDA line — apt `cmake
   libeigen3-dev libcgal-dev libopencv-dev libboost-*` etc., clone OpenMVS **`v2.4.0`** (+ VCG),
   `cmake -DOpenMVS_USE_CUDA=ON`, install to `/opt/openmvs`. This layer is the ~30-min one;
   `--cache-from :latest` keeps it out of every push after the first.
2. `FROM colmap/colmap:20260729.7651` (Ubuntu 24.04, CUDA 12.9.1 **runtime** — it has no `nvcc`, which
   is why OpenMVS compiles in stage 1) — copy `/opt/openmvs/{bin,lib}` in, apt the OpenMVS runtime
   libraries and `python3.12`, `pip install ./gpu-worker` + `trimesh pillow numpy boto3 sqlalchemy
   psycopg2-binary pydantic-settings`; `CMD ["python", "main.py"]`.

Target size ≈ 7 GB. The `worker.yml` transcription build moves to the same root-context form.

## 3. Controller family fix and the ledger

### Schema

Alembic `m3n4o5p6q7r8_add_gpu_sessions_family`: `gpu_sessions.family VARCHAR(32) NOT NULL DEFAULT
'transcription'`. Logical names — `transcription` | `photogrammetry` — not ECS family strings, so
the backfill default is environment-neutral. The worker's `GpuSessionStore` never sees the column;
the API stamps it at create and the worker finds its row by `task_arn`.

### `GpuSessionRepository(db, family)`

| Method | Scope | Why |
|---|---|---|
| `create` | stamps `family` | |
| `close_open_sessions` | **this family** | the hazard from UI-spec §7: transcription's empty `ListTasks` must not close a photogrammetry row |
| `extend_warm`, `warm_count_for_user_since` | this family | warm is a per-worker concept |
| `hours_between`, `sessions_since` | **all families** | one pool, one daily/monthly budget |

`hours_between` also takes the queued phantom-hours fix: a row's span starts at
`coalesce(started_processing_at, started_at)` and rows with `instance_id IS NULL` contribute 0 —
a session that never got an instance costs nothing. The ~2 min between instance-up and the
worker's claim is under-counted; accepted (TODO decision, 2026-08-27).

### `GpuController`

- `GpuController(repo, launcher, settings, family, cost_client=None, now=…)`.
- `_state_cache: dict[str, tuple[float, list[str]]]` keyed by `family`; every read and every
  invalidation in `get_state` / `ensure_worker` goes through the key.
- `_check_caps` unchanged (already reads the summed hours).
- `GpuSessionSummary` carries `family` so the usage data says which worker burned the hours; the
  panel itself shows totals only.
- `deps.py` (transcribe: `family="transcription"`; photogrammetry: `family="photogrammetry"`).

### Two families, one pool

`gpu_max_size` stays 2. Each task requests one whole GPU; a photogrammetry launch while
transcription is busy drives the ASG to 2 — two g4dn.xlarge is exactly the account's current
On-Demand G/VT quota; a third family needs a quota increase.

### Status bar

`GET /gpu/state` and `POST /gpu/warm` accept `?family=` (default `transcription`, enum-validated).
`GpuStatusBar` gets a `family` prop; the Scan page passes `photogrammetry` and hides *Warm* — a
30-min batch job gains nothing from a warm box. This closes the "wrong worker's bar" item without
the shared-abstraction rewrite.

## 4. Infrastructure, CI, AMI

### `infra/modules/photogrammetry` (new; instantiated in the `transcription-prod` environment)

Inputs: bucket id/arn, cluster id, VPC/subnets, `database_url_secret_arn`, GitHub org/repo,
`image_tag`, `idle_exit_seconds`, `max_lifetime_seconds`, `job_timeout_seconds`, `alarm_email`.

| Resource | Notes |
|---|---|
| ECR `photogrammetry-<env>-worker` | lifecycle keep 2 |
| SQS `photogrammetry-<env>` + DLQ | retention 4 d, `maxReceiveCount` 3, visibility 600 s |
| Task definition `photogrammetry-<env>-worker` | EC2, `bridge`, `resourceRequirements GPU 1`, `memory 14000` (dense reconstruction is RAM-bound; one task per g4dn.xlarge), env = §2 Settings, `DATABASE_URL` from the shared secret, `CostCenter = gpu` |
| IAM `worker_execution`, `worker_task` | task: `s3:GetObject/PutObject` on `photogrammetry/*` and `samples/photogrammetry/*`, `s3:ListBucket` (prefix-conditioned), `sqs:ReceiveMessage/DeleteMessage/ChangeMessageVisibility` on its queue; nothing else |
| IAM `photogrammetry-<env>-worker-github-actions` | OIDC; ECR push, `RegisterTaskDefinition`, `PassRole` on its own two roles — the trimmed shape |
| Inline policy on the API task role | `RunTask` on `task-definition/photogrammetry-<env>-worker:*`, `PassRole` on the two worker roles. The transcription module's grant is scoped to its own family, so without this `RunTask` is denied |
| Log group `/ecs/photogrammetry-<env>-worker` | 30 d |
| CloudWatch alarm | DLQ `ApproximateNumberOfMessagesVisible ≥ 1` → the existing `gpu-<env>-alerts` SNS topic |

In the transcription module (owner of the bucket): lifecycle rule `photogrammetry/` → expire 30 d.
This expires `output/mesh.glb` and `preview.png` as well as the inputs — a job older than 30 days
shows `complete` but its mesh URL 404s. Accepted for v1; follow-up in `docs/TODO.md`.

### API environment (`environments/prod`)

`GPU_PHOTOGRAMMETRY_TASK_FAMILY` and `PHOTOGRAMMETRY_SQS_QUEUE_URL` as locals, the way
`worker_task_family` is today (cross-state by name). Real values live in cm/aws
`overlay/chat/terraform.tfvars`.

### CI

`.github/workflows/photogrammetry-worker.yml` = `worker.yml` with repository, family and role
secret (`AWS_DEPLOY_ROLE_ARN_PHOTOGRAMMETRY`) swapped, `-f photogrammetry-worker/Dockerfile .`,
`paths:` on `photogrammetry-worker/**` and `gpu-worker/**`. `worker.yml` gains the root-context
build and the `gpu-worker/**` path trigger.

### AMI bake

`scripts/deploy/build-gpu-ami.sh <base-ami> <image-uri>[,<image-uri>…] …` pulls every image; the
AMI name and `Image` tag come from the first. One bake carries both images (≈ 7.7 + 7 GB on the
80 GB root).

### Cutover order (the runbook's job)

1. API deploy with the migration (§3) and the family fix — `GPU_PHOTOGRAMMETRY_TASK_FAMILY` still
   empty; transcription behaviour unchanged, `confirm` still 503.
2. Terraform apply (`transcription-prod`, then `prod` for the API env locals — still empty).
3. Worker image push (workflow) → task-def revision.
4. AMI bake with both images → `gpu_ami_id` in tfvars → apply.
5. API deploy with the family and queue URL set. Acceptance (§5).

**Rollback** = empty `GPU_PHOTOGRAMMETRY_TASK_FAMILY` (API redeploy). The queue drains in 4 days;
nothing else to undo. The transcription worker's behaviour after step 1 is the same code path
with `family="transcription"` — the only observable difference is the new column.

## 5. Testing and acceptance

### Unit — no GPU, no AWS, runs in CI

- `gpu-worker/tests/`: moved SpotWatcher tests; loop tests for idle exit, max lifetime, warm
  extension, interrupt between messages (today only exercised in prod).
- `photogrammetry-worker/tests/`: handler sequencing with a fake runner — the row walks
  `sfm → dense → mesh → texture → complete`; a stage error → `failed` + message acked; an
  interrupt → `queued` + not acked; registration threshold (60 %); `RefineMesh` skip (> 100);
  deadline kills the subprocess and fails the job; GLB export from a 4-triangle OBJ + 2×2 PNG
  fixture via trimesh; preview resize keeps aspect.
- `chat-api`: `close_open_sessions` leaves the other family's row open; `hours_between` sums
  across families and gives 0 for `instance_id IS NULL`; controller cache isolation across two
  controllers; publisher called after commit on confirm and sample; `/gpu/state?family=`
  validation. The existing suite (144) stays green.

### Local, before any deploy

`docker build` of the worker on fitlet and a CPU run (`COLMAP_USE_GPU=0`) of the 22-photo sample
through the whole pipeline against the local API + throwaway pgvector container — slow, but the
proof that the container works before a bake is spent. `alembic upgrade → downgrade → upgrade`
on the same container.

On fitlet the image build and CPU smoke were deferred (root disk ~7 GB free vs ≈10 GB of images);
the first build runs in CI and the CPU smoke is a runbook step.

### Acceptance — Neil drives the UI, Claude verifies CLI (as runbook §9)

1. Sample job → `processing` with stages advancing in the UI → `complete`, the cat in the viewer.
2. A real 20–40 photo upload to completion.
3. A deliberate failure (5 near-identical photos) → `failed` with a readable message, message
   acked, no retry loop, DLQ empty.
4. Ledger row `family = photogrammetry` with `instance_id`, closed `idle`.
5. One transcribe job afterwards — unaffected.

Budget ≈ 1 GPU-hour.

## 6. Out of scope (TODO)

Headless mesh-render previews; Gaussian splats; `RefineMesh`/`DensifyPointCloud` tuning; more
than one job per worker; per-family budgets; the shared job-service abstraction across
transcribe and photogrammetry; `pending` expiry (separate TODO item).
