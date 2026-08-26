# Photogrammetry UI — design spec

**Date:** 2026-08-26 · **Status:** implemented 2026-08-26 (plan docs/superpowers/plans/2026-08-26-photogrammetry-ui.md); worker spec pending

## Goal

Add a photogrammetry feature to chat.peaslee.org shaped like the transcribe feature: a user drops a
set of photos, a job runs on the shared GPU pool, and the result — a textured mesh — renders in the
browser. **This spec covers the web interface, the API contract, and the local-dev mock only.** The
real reconstruction worker (COLMAP → OpenMVS → texturing, packaged as an ECS task on the
`gpu-<env>` capacity provider) is a separate spec; this one fixes the contract it will implement.

Decisions from the brainstorm:

| # | Question | Decision |
|---|---|---|
| 1 | What a finished job shows | **In-browser mesh viewer** (`<model-viewer>`, GLB). No Gaussian splats in v1. |
| 2 | Input | **Multi-file drop** of JPG/PNG; one presigned PUT per image. No ZIP, no video. |
| 3 | Sample data | **Neil shoots 12–20 photos** of a small object; a generated placeholder GLB + preview stand in for the output. |
| 4 | Mock layers | **API-level mock only** (`USE_MOCK_PHOTOGRAMMETRY`). No hand-written MSW handlers, no worker skeleton. |
| 5 | Structure | **Own vertical mirroring transcribe** (approach A). Nothing in transcribe is refactored. |

## 1. Contract

### Job model — table `photogrammetry_jobs`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | `UUIDMixin` |
| `user_id` | str(256), indexed | Cognito `sub` |
| `name` | str(200) | user-given; default `Scan <YYYY-MM-DD HH:MM>` |
| `status` | enum `photogrammetry_job_status` | see state machine |
| `stage` | str(20), nullable | `sfm` · `dense` · `mesh` · `texture`; set only while `processing` |
| `image_count` | int | 5 ≤ n ≤ `PHOTOGRAMMETRY_MAX_IMAGES` |
| `input_prefix` | str(1024) | `photogrammetry/<user_id>/<job_id>/input/` |
| `mesh_s3_key` | str(1024), nullable | `photogrammetry/<user_id>/<job_id>/output/mesh.glb` once complete |
| `preview_s3_key` | str(1024), nullable | `…/output/preview.png` once complete |
| `error_message` | text, nullable | set with `failed` |
| `created_at`, `updated_at`, `completed_at` | timestamptz | as `transcription_jobs` |

Images are **not** rows. Input keys are `input/0001.jpg … input/NNNN.<ext>` (zero-padded, original
extension lower-cased); `image_count` plus a prefix listing is all the worker needs. There is no
events table in v1 — `stage` on the row drives the progress UI.

### State machine

```
pending ──confirm──► queued ──worker picks up──► processing ──► complete
                                                   │  stage: sfm → dense → mesh → texture
                                                   └──────────► failed (error_message)
```

- `pending`: row exists, presigned URLs issued, uploads in flight.
- `queued`: confirmed; waiting for a GPU task. The real worker sets `processing`; the mock does so on
  a timer.
- Active = `pending | queued | processing`. Per-user active cap = existing `MAX_CONCURRENT_JOBS`.

### Storage layout (audio bucket, same bucket transcribe uses)

```
photogrammetry/<user_id>/<job_id>/input/0001.jpg …
photogrammetry/<user_id>/<job_id>/output/mesh.glb
photogrammetry/<user_id>/<job_id>/output/preview.png
samples/photogrammetry/images/0001.jpg …          (shared sample set, uploaded once by hand)
```

Deleting a job deletes the row only; objects are left to the bucket lifecycle rule, as transcribe
does. (Adding `photogrammetry/` to that rule is part of the worker spec.)

### Endpoints — `/api/v1/photogrammetry`, Bearer auth as transcribe

| Method & path | Request | Response | Notes |
|---|---|---|---|
| `POST /jobs` | `{name?, filenames: string[]}` | `202 {job_id, uploads: [{filename, key, url}]}` | one presigned PUT per filename, TTL 15 min; `len(filenames)` outside `[5, PHOTOGRAMMETRY_MAX_IMAGES]` → 422; extension not in `jpg jpeg png` → 422; cap → 429 `ConcurrentJobLimitExceeded` |
| `POST /jobs/{id}/confirm` | — | `202` | real: listing `input_prefix` must return ≥ `image_count` keys else 409 `UploadIncomplete`; then `queued` and `ensure_worker("job", user)` on a `GpuController` bound to `GPU_PHOTOGRAMMETRY_TASK_FAMILY`; **empty task family → 503 `photogrammetry worker not deployed`** (explicit stub, job stays `pending`). mock: trusts the sink, `queued`, schedules the mock walk |
| `GET /jobs` | `?cursor&limit` | `{items: [JobStatus], next_cursor}` | user's jobs, newest first; same keyset cursor as transcribe |
| `GET /jobs/{id}` | — | `JobStatus` | 404 if not the caller's |
| `DELETE /jobs/{id}` | — | `204` | row only |
| `POST /jobs/sample` | — | `202 {job_id}` | seeds from the shared sample set and confirms |
| `GET /jobs/{id}/mesh` | — | `{url, expires_at}` | presigned GET (mock: sink GET URL); 409 unless `complete` |

`JobStatus` = `{job_id, name, status, stage, image_count, preview_url (nullable, presigned/sink GET),
error_message, mock: bool, created_at, updated_at, completed_at, worker_state?, estimated_wait_seconds?,
gpu_notice?}` — `job_id` and the three GPU hints follow transcribe's response shape. `mock` is `true`
when served by the local service so the UI can label the placeholder result.

## 2. Backend (`chat-api`)

Files, mirroring the transcribe layout:

| File | Content |
|---|---|
| `app/models/photogrammetry.py` | ORM model above; export from `models/__init__.py` |
| `app/db/migrations/versions/l2m3n4o5p6q7_add_photogrammetry_jobs.py` | table + enum + `ix_photogrammetry_jobs_user_id` |
| `app/schemas/photogrammetry.py` | `JobCreateRequest`, `UploadTarget`, `JobCreateResponse`, `JobStatusResponse`, `JobListResponse`, `SampleJobResponse`, `MeshUrlResponse` |
| `app/repositories/photogrammetry.py` | `create_job`, `get_job_for_user`, `list_jobs_for_user`, `count_active_jobs`, `update_job_status` (status, stage, keys, error), `delete_job`. Queries only. |
| `app/services/photogrammetry_service.py` | `PhotogrammetryService` + `LocalPhotogrammetryService` (below) |
| `app/api/v1/photogrammetry/__init__.py`, `deps.py`, `jobs.py` | thin router; `deps.get_photogrammetry_service` returns the mock when `USE_MOCK_PHOTOGRAMMETRY`; mounted in `api/v1/router.py` under `/photogrammetry` |
| `app/api/v1/transcribe/__init__.py` | the `dev-upload` sink is included when **either** `use_mock_transcription` **or** `use_mock_photogrammetry` is set; its path stays `/api/v1/transcribe/dev-upload/{path}` |
| `app/config.py`, `.env.example` | new settings (below) |
| `app/assets/photogrammetry/images/*.jpg`, `mesh.glb`, `preview.png` | sample assets (§4) |

**`PhotogrammetryService`** (real): uses the existing `AudioStorageService` for presigned URLs and
prefix listing — it is already a generic S3 helper on the audio bucket; it is not renamed. It gains
`generate_presigned_download_url(key, ttl)` (all three storage classes) and the local/mock classes
gain `write_object(key, bytes)`. `deps.py` builds a second `GpuController` whose `EcsWorkerLauncher`
is bound to `settings.gpu_photogrammetry_task_family` (same cluster, capacity provider and
`gpu_sessions` ledger/caps as transcribe); when that setting is empty the service gets `gpu=None`
and `confirm` raises `WorkerNotDeployed` (→ 503). `create_sample_job` builds a job whose
`input_prefix` is `settings.photogrammetry_sample_prefix + "images/"` and confirms it.
The `dev-upload` sink's GET now serves the stored file (with a guessed content type) when it exists,
so the viewer can load the mock GLB/preview; a missing file still returns an empty 200.

**`LocalPhotogrammetryService(PhotogrammetryService)`** (mock): presigned URLs point at the
`dev-upload` sink under `MOCK_UPLOAD_BASE_URL` (as `LocalTranscriptionService` does); `confirm` sets
`queued` and `asyncio.create_task(self._mock_process_job(job_id))`, which sleeps
`MOCK_PHOTOGRAMMETRY_STAGE_DELAY_SECONDS` (default 2) per step through `processing/sfm → dense →
mesh → texture`, copies `app/assets/photogrammetry/{mesh.glb,preview.png}` into the sink's local
storage under the job's `output/` keys, and sets `complete`. `create_sample_job` copies the asset
images into the sink under the job's `input/` prefix first. `mock: true` on every status response.

**Settings**

| Variable | Default | Purpose |
|---|---|---|
| `USE_MOCK_PHOTOGRAMMETRY` | `false` | select `LocalPhotogrammetryService`; also registers the sink |
| `MOCK_PHOTOGRAMMETRY_STAGE_DELAY_SECONDS` | `2` | per-stage delay in the mock walk |
| `PHOTOGRAMMETRY_MAX_IMAGES` | `150` | upper bound on `filenames` |
| `PHOTOGRAMMETRY_SAMPLE_PREFIX` | `samples/photogrammetry/` | shared sample set location in the bucket |
| `GPU_PHOTOGRAMMETRY_TASK_FAMILY` | `""` | ECS task family for the worker; empty = not deployed (503 on confirm) |

**Errors** map onto the existing `core/exceptions.py` classes where they exist
(`ConcurrentJobLimitExceeded` → 429, not-found → 404) plus two new ones: `UploadIncomplete` (409)
and `WorkerNotDeployed` (503). Validation (image count, extension) is Pydantic → 422.

## 3. Frontend (`chat-vue`)

- **Route** `/photogrammetry`, name `photogrammetry`, lazy-loaded like `/transcribe`. Third tab in
  `ConversationSidebar` after Chat / Transcribe, labelled **Scan**, active-state styling copied from
  the Transcribe tab.
- **`lib/photogrammetryApi.ts`** — the seven calls over the shared `apiClient` (so the traffic
  recorder and MSW replay cover them with no extra work). Uploads go straight to the presigned URLs
  with `fetch` PUT, as audio does; MSW's existing "stub any presigned PUT with 200" rule applies.
- **`stores/photogrammetry.ts`** — `jobs`, `selectedJobId`, `uploadProgress {done, total}`,
  `toasts`. Actions: `loadJobs(force)`, `createJob(name, files)` = POST → PUT the files 4 at a time
  updating `uploadProgress` → confirm → start polling; `pollJob(id)` every 3 s while active, stops on
  `complete | failed`; `resumePollingForActiveJobs()` on mount; `deleteJob`; `createSampleJob`;
  `fetchMeshUrl(id)` (cached per job until `expires_at`). Same shape as `stores/transcribe.ts`
  without speakers.
- **`views/PhotogrammetryView.vue`** — `GpuStatusBar` (reused unchanged) over a resizable
  `ScanSidebar` + `ScanDetailView`, with the same drag-handle and toast code as `TranscribeView`
  (copied, not shared — a shared layout component is a later refactor if a third tab appears).
- **`components/photogrammetry/`**
  - `ImageDropzone.vue` — multi-file input + drag/drop, accepts `image/jpeg, image/png`, shows count
    and small thumbnails (object URLs, revoked on unmount), enforces 5–150 client-side with an
    inline message.
  - `NewScanForm.vue` — name (prefilled with the default), dropzone, **Start scan**; disabled while
    uploading; shows `uploadProgress`.
  - `ScanSidebar.vue` — job list of `ScanJobCard.vue` (name, status badge, image count, age) +
    **New** and **Sample** buttons.
  - `ScanStatusBadge.vue` — status colour + text (`processing · dense` while processing; the
    worker-state label while queued/processing with the worker off or starting).
  - `StageStrip.vue` — the four-step strip (sfm · dense · mesh · texture) with the current step
    highlighted; shown in the detail view while a job is active.
  - `ScanDetailView.vue` — header (name, badge, delete), then: form when creating; preview image +
    stage strip while active; `MeshViewer` when complete; error box when failed.
  - `MeshViewer.vue` — wraps `<model-viewer>` from `@google/model-viewer` (one new dependency):
    `camera-controls auto-rotate shadow-intensity="1"`, `src` = the presigned GLB URL, poster =
    `preview_url`, fills the pane. Shows a one-line notice *"Placeholder mesh — served by the local
    mock, not reconstructed from these photos"* when `job.mock` is true.
- **`vite.config.ts`** — `vue({ template: { compilerOptions: { isCustomElement: t => t === 'model-viewer' } } })`.
- **`types/index.ts`** — `PhotogrammetryJob`, `PhotogrammetryJobStatus`, `PhotogrammetryStage`,
  `UploadTarget`.

## 4. Sample data and local dev

- **`scripts/dev/make-photogrammetry-sample.py`** (committed; Python, Pillow + trimesh):
  - `--photos <dir>`: reads Neil's phone photos, downscales to 640 px on the long side, **strips all
    EXIF** (GPS included — the repo is public), re-encodes JPEG q=80, writes
    `chat-api/app/assets/photogrammetry/images/0001.jpg…`. Target ≤ 2 MB total; warns above.
  - `--synthetic`: emits 12 PIL-drawn placeholder "views" of a coloured shape instead, so the feature
    is runnable before the photos land. Replaced by the real set as soon as it exists.
  - Always: builds `mesh.glb` (a small procedural textured object via `trimesh`, a few KB) and
    renders `preview.png` from its vertices with a plain orthographic projection in Pillow — no
    OpenGL. Both are unmistakably placeholders and are labelled so in the UI (`mock: true`).
  - Prints the one-time `aws s3 sync … s3://<audio-bucket>/samples/photogrammetry/images/` line for
    the prod sample set. Neil runs it; the script never touches AWS.
- **Local run:** `chat-api`: `USE_MOCK_PHOTOGRAMMETRY=true` in `.env` (added to `.env.example`),
  `docker compose up`; `chat-vue`: `npm run dev`. **Sample** creates a job that walks
  `queued → sfm → dense → mesh → texture → complete` in ~10 s and the viewer shows the placeholder
  GLB. A new scan does the same after its uploads hit the sink.
- **Docs:** `docs/mock-api.md` gains a *Photogrammetry* paragraph; `chat-api/CLAUDE.md` (layout,
  env table, mock notes) and `chat-vue/CLAUDE.md` (components, store) are updated; root `CLAUDE.md`
  runtime-flow gets one line.

## 5. Testing

- **API unit tests** (`tests/unit/api/test_photogrammetry_jobs.py`,
  `tests/unit/services/test_photogrammetry_service.py`), mirroring the transcribe tests:
  create (happy path returns one upload per filename; 4 files → 422; bad extension → 422; cap →
  429); confirm (mock walks to `complete` with delay 0; real with empty task family → 503; real with
  a missing object → 409); status/list/delete ownership (another user's job → 404); sample job
  (mock: images copied, job reaches `complete`); mesh URL (409 before complete).
- **Vue:** the repo has no vitest — `vue-tsc --noEmit` and `vite build` in CI as today, plus a
  manual walkthrough (sample job, new scan with the asset images, delete) recorded in the PR.
- **Migration:** `alembic upgrade head` then `downgrade -1` clean against the compose Postgres.

## 6. Out of scope (each its own spec)

- The `photogrammetry-worker` container (COLMAP/OpenMVS/texturing), its ECS task definition and
  Terraform, the AMI bake entry, `GPU_PHOTOGRAMMETRY_TASK_FAMILY` in prod.
- Bucket lifecycle rule for `photogrammetry/`.
- Gaussian splats, video input, ZIP input, job events / SSE, shared GPU-job abstraction across
  transcribe and photogrammetry.
