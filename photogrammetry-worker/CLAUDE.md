# photogrammetry-worker

Standalone Python worker: a run-to-completion ECS task on the shared `gpu-<env>` capacity
provider, launched per job by the API's `RunTask` and exiting itself when idle (see Lifecycle
below). No HTTP server. Takes a confirmed job's photos from S3, runs COLMAP → OpenMVS → texturing,
and writes `mesh.glb` + `preview.png` back to S3, walking the job row through
`processing/sfm → dense → mesh → texture → complete`.

## Key Commands

```bash
# Install dependencies (dev)
cd photogrammetry-worker && uv sync --extra dev

# Run tests (no AWS creds, DB, COLMAP, or OpenMVS needed)
uv run pytest -q

# Build Docker image (build context is the repo root)
docker build -f photogrammetry-worker/Dockerfile .

# Run container locally
docker run --env-file .env photogrammetry-worker
```

**The image has not been built locally.** This machine's root disk had ~7 GB free when this
worker was implemented (2026-08-27); the COLMAP base image alone is 3.2 GB and the CUDA `-devel`
build stage adds several GB more, so `docker build` was never run here. `docker build --check
-f photogrammetry-worker/Dockerfile .` (BuildKit lint, no image pull of layers) reported no
warnings. The first real build happens in CI on push (`.github/workflows/photogrammetry-worker.yml`).
The CPU smoke test below is the documented procedure — run it from the runbook once disk is
available (fitlet or a box with headroom), not before.

### CPU smoke test (deferred — run when disk allows)

Proves the tool chain and the file names in the reconstruction stages end to end, on the
committed sample (22 photos, `chat-api/app/assets/photogrammetry/images/`), without a GPU:

```bash
DOCKER_BUILDKIT=1 docker build -f photogrammetry-worker/Dockerfile -t photogrammetry-worker:dev . 2>&1 | tail -20
docker run --rm photogrammetry-worker:dev colmap -h | head -3
docker run --rm photogrammetry-worker:dev TextureMesh --help | head -3

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

Expected: build succeeds, both binaries print usage; `registered N` with N ≥ 14 (60% of 22),
a non-trivial `mesh.glb`, and `preview.png`. Slow on CPU (tens of minutes). If an OpenMVS output
name differs, fix `pipeline/openmvs.py` + its test.

## Environment Variables

| Variable | Default | Required |
|---|---|---|
| `DATABASE_URL` | — | yes |
| `AUDIO_BUCKET_NAME` | — | yes |
| `PHOTOGRAMMETRY_SQS_QUEUE_URL` | — | yes |
| `AWS_REGION` | `us-east-1` | no |
| `IDLE_EXIT_SECONDS` | `900` | no |
| `MAX_LIFETIME_SECONDS` | `10800` | no |
| `PHOTOGRAMMETRY_JOB_TIMEOUT_SECONDS` | `3600` | no |
| `SQS_VISIBILITY_TIMEOUT` | `600` | no |
| `SQS_VISIBILITY_EXTENSION_INTERVAL` | `300` | no |
| `WORK_DIR` | `/tmp/pg` | no |
| `COLMAP_USE_GPU` | `1` | no — `0` runs SIFT/matching on CPU (fitlet smoke test) |

`DATABASE_URL` may use either `postgresql+asyncpg://` or `postgresql+psycopg2://` scheme —
`gpu_worker.db.make_session_factory` normalises it to psycopg2 automatically.

## Pipeline

| Step | Row `stage` | Command(s) | Rule |
|---|---|---|---|
| load | — | `SELECT … FOR UPDATE`; if status ∉ {`queued`, `processing`} → ack and return | idempotent on redelivery |
| fetch | `sfm` (status → `processing`) | list `input_prefix`; download; fail if fewer than `image_count` objects | |
| SfM | `sfm` | `colmap feature_extractor` (SIFT, GPU) → `colmap exhaustive_matcher` → `colmap mapper` | take the model with the most registered images; **fail if registered < 60% of `image_count`** ("Only N of M photos could be matched — add overlap and try again") |
| dense | `dense` | `colmap image_undistorter` → `InterfaceCOLMAP` → `DensifyPointCloud --resolution-level 2` | resolution level fixed for the 16 GB T4 |
| mesh | `mesh` | `ReconstructMesh` → `RefineMesh` | **`RefineMesh` skipped when `image_count` > 100** (time cap) |
| texture | `texture` | `TextureMesh` → `mesh_textured.obj` + atlas PNG → `trimesh.load(...).export("mesh.glb")` | GLB via trimesh (pure Python, no EGL); `preview.png` = first input photo resized to 640 px on the long edge |
| publish | — | upload `output/mesh.glb`, `output/preview.png`; row → `complete`, `mesh_s3_key`, `preview_s3_key`, `completed_at`; ack | |

## Failure mapping

| Event | Row | Ack? |
|---|---|---|
| Any `StageError`, `JobTimeout`, or other exception in a stage | `failed`, `error_message` = the rule's text or the first line of the tool's stderr (≤ 1000 chars) | **acked** — a deterministic failure must not retry three times on a $0.53/h box |
| Spot interruption notice (`gpu_worker.sqs.Interrupted`) | reset to `queued`, `stage = NULL` | **released**, not acked — `SpotWatcher` has already released the SQS message with `VisibilityTimeout=0`; next worker restarts from scratch |
| Worker dies mid-job (OOM, crash) | stays `processing` | redelivered after the visibility timeout (≤ 3 times, then DLQ) — the load step accepts `processing` and restarts |

Scratch (`WORK_DIR/<job_id>`) is removed in every case.

## Lifecycle

Lifecycle lives in `../gpu-worker` — run its tests there.
