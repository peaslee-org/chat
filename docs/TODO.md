# TODO / backlog

Grouped by **what a change forces you to rebuild or redeploy**, so items can be batched. Worker-image
items cost an ECR push + task-def revision (automatic on push) and, to keep cold starts from pulling,
an AMI re-bake (`scripts/deploy/build-gpu-ami.sh`); API items an ECS deploy; Vue items a CloudFront
deploy; infra items a Terraform apply. `deploy.yml` orders the first three; see
`docs/runbooks/deploy.md`.

## Worker image (batch these — rebake the GPU AMI once)

- [ ] **Immediate release leaves the message invisible for up to `SQS_VISIBILITY_TIMEOUT` (600 s).**
  Only `SpotWatcher` calls `change_message_visibility(0)`; the shell's `except Interrupted` should
  do the same when `ReleaseWatcher.abort` is set so the next worker gets the job at once.
- [ ] **GPU idle-release countdown that survives polling.** Today `warm_until` is only in the
  *Warm* response; the 30 s `/gpu/state` poll returns `null`, so the bar's `idle-out in mm:ss`
  vanishes, and a job-launched worker never has one. Real release time is
  `max(last_work + IDLE_EXIT_SECONDS, warm_until)`, known only to the worker. Plan: add
  `gpu_sessions.idle_release_at`, written on each heartbeat; `get_state()` returns
  `max(idle_release_at, warm_until)` as `warm_until`; bar keeps the label across polls.
- [ ] **Root-cause OpenMVS seam leveling in our build.** Both passes rewrite every face's pixels as ~0
  (black faces, stray saturated texels) in the v2.4.0-on-noble image (OpenCV 4.6, GCC 13); the raw
  patch copy is right. Excluded on the sample scan: sharpening, OpenMP (`--max-threads 1`), either
  pass alone. Left: the Eigen sparse solves (global adjustments, local Poisson blend) or the bilinear
  sampler they share. Reproduces in ~1 min on the fitlet: `docker run --rm -e LD_LIBRARY_PATH=/opt/cuda-stubs
  -v <smoke>:/tmp/pgsmoke --entrypoint TextureMesh <image> /tmp/pgsmoke/work/dense/scene_dense.mvs -m
  …/scene_dense_mesh.ply -w …/dense -o …/exp/scene_textured.mvs --export-type obj --cuda-device -2 [flags]`,
  then sample the atlas at face centroids. Try: upstream's own ubuntu Dockerfile (newer OpenCV), a
  Debug build with `-ffast-math` off, and `git bisect` between v2.3.0 and v2.4.0. Re-enable leveling
  when fixed (visible patch seams until then).
- [ ] **Gravity-align the reconstruction.** After `27a23f1` orientation follows the first photo's roll
  (portrait vs landscape shots come out sideways). Options: COLMAP `model_orientation_aligner`
  (Manhattan-world; may fail on organic subjects), or a rotate control in `MeshViewer.vue`.
- [ ] Headless mesh-render `preview.png` (pyrender + EGL) — replaces the first-photo preview
  (worker spec decision 4).
- [ ] Mixed cameras: `--ImageReader.single_camera_per_folder` with one folder per pixel size
  instead of skipping.
- [ ] `photogrammetry-worker/tests/test_handler.py` takes minutes instead of seconds when the
  handler's generic-exception path is hit repeatedly (seen 2026-08-29 while a test fixture was
  broken) — probably a retry/cleanup branch sleeping; find and cap it.

## API (chat-api)

- [ ] **`POST /gpu/release` 200 means "flag written", not "worker acknowledged"** — a worker on an image
  without the watcher never reads it. Either return the session's `release_requested_at`/`ended_at`
  on a follow-up `GET /gpu/state`, or have the controller fall back to `StopTask` when the row is
  still open after N seconds.
- [ ] `repositories/transcription.py` `list_jobs` / `list_speakers`: keyset cursor is built from
  the popped overflow row, so page 2 skips one item. Fixed in `repositories/photogrammetry.py`
  (cursor from the last *returned* row); port the fix + test.
- [ ] `pending` photogrammetry jobs never expire and count against `MAX_CONCURRENT_JOBS`
  (presigned PUTs live 15 min). Exclude `pending` older than the URL TTL from
  `count_active_jobs`, or sweep. Same precedent in transcribe.
- [ ] Malformed `cursor` → 500 (both repositories); return 422.
- [ ] Mock walk (`LocalPhotogrammetryService`) has no `failed` transition; a mid-walk exception
  leaves the job `processing` (transcribe mock does the same). The mock also never writes
  `photo_status`, so the matched/not-matched tiles can't be seen locally.
- [ ] Photogrammetry rows outlive their S3 objects (30-day lifecycle on `photogrammetry/`): mark
  rows `expired` (or split the output prefix — a contract change) so the viewer doesn't get a 404.
- [ ] Thumbnails for a 150-photo scan are generated on the first `/photos` call (≈3–5 s in one
  request). Fine for now; if it bites, kick generation off at `confirm` time instead.

## Vue (chat-vue)

- [ ] **Transcribe "Try the sample" still submits blind** (silently a no-op while a sample job is
  pending). The Scan tab's Sample now opens a preloaded form; give Transcribe the same treatment.
- [ ] Sidebar placeholder shows "0 photos" for a few seconds after starting a sample scan (the
  placeholder row doesn't know the count until the first poll) — pass the sample's `image_count`.
- [ ] Photogrammetry store: no polling cutoff for a job stuck in `pending`; sibling uploads are
  not cancelled when one fails; dropzone not keyboard-focusable; dragover flicker over children.
- [ ] Delete "✕" in `RunSidebar` / `ScanJobCard` is a span inside a button (not keyboard-operable).
- [ ] `npm run type-check` and the `vue-tsc` step of `npm run build` check nothing — the root
  `tsconfig.json` is solution-style (`files: []`) and neither passes `-p tsconfig.app.json`/`-b`.
  Make the script `vue-tsc -p tsconfig.app.json --noEmit` (four pre-existing errors in
  `transcribe/*.vue` will surface). `npm run test` (vitest) exists since 2026-08-29.

## CI

- [ ] When the API job of a Deploy run fails, the surfaces behind it are skipped and a code-only fix
  redeploys only what changed — the skipped ones need `gh workflow run Deploy -f vue=true`
  (runbook). Consider a "redeploy what the last failed run skipped" dispatch input, or making the
  `changes` job compare against the last *successful* deploy's sha instead of `before`.

## Infra (terraform)

- [ ] **ECS managed scaling launches 2 instances for 1 task** from zero (observed every cold start
  2026-08-26 → 29); the spare idles ~10 min until scale-in. Check the capacity provider's
  `minimum_scaling_step_size` / target and the estimate with mixed instance types.
- [ ] **~15 min scale-in lag after the worker exits** (ECS managed scale-in = 15 low datapoints;
  exit 16:38 → ASG 0 at ~16:55 on 2026-08-29). Options: worker terminates its own instance on exit
  (`ec2:TerminateInstances` scoped by tag, `InstanceInitiatedShutdownBehavior`), or a custom
  scale-in alarm on `CapacityProviderReservation` with fewer datapoints. Note this window is also
  what makes a **warm** start possible (measured since PR #13) — shortening it trades warm starts for cost.
- [ ] `gpu_on_demand_percentage` back to 0 once spot placement scores recover.
- [ ] **`scripts/deploy/migrate.sh` is dead**: it execs `uv run alembic …`, but the runtime stage of
  `chat-api/Dockerfile` never copies `uv`. Migrations run from `scripts/entrypoint.sh` at container
  start, so the script is only for a manual re-run. Fix: `CMD="/app/.venv/bin/python -m alembic -c
  /app/app/db/alembic.ini upgrade head"`, and say in the header that the entrypoint already does this.
- [ ] Photogrammetry: `gpu_max_size` 2 — two g4dn.xlarge is exactly the account's current
  On-Demand G/VT quota; a third family needs a quota increase.

## Local dev

- [ ] `chat-api/docker-compose.yml` uses `postgres:16-alpine`, which lacks pgvector — a clean
  `docker compose up` + `alembic upgrade head` fails on the speaker-embedding migration. Switch
  to `pgvector/pgvector:pg16`. (Until then: `docker run -d --name chatapi-pg-dev -p 5433:5432 -e
  POSTGRES_PASSWORD=… -e POSTGRES_DB=chatapi pgvector/pgvector:pg16`, which is what `.env` points at.)
- [ ] Presigned PUT TTL (15 min) is tight for 150 photos on a slow link; consider 30–60 min for
  the PUT side only.
- [ ] `chat-api/.env` pins `GPU_WAIT_ESTIMATE_*` to the old 120/180 s; drop them so local dev uses
  the code defaults (420 / 90).

## Recently done (2026-08-28 → 30)

- 2026-08-30 worker batch (one AMI re-bake): GLB atlases cropped to their used UV box, capped at
  `TEXTURE_MAX_SIZE`² pixels and embedded as JPEG q85; sample 3.28 → 2.17 MB. Inspection showed
  OpenMVS atlases were already JPEG and the bulk was unwelded geometry (3 verts/face) — vertices
  sharing position + UV are now welded (sample geometry 2.07 → ~0.7 MB; 51-photo set was 45 MB,
  measure again). Draco / quantised attributes still open if it's not enough. Photogrammetry fails
  the row on permanent S3 errors (`TRANSIENT_S3_CODES` allowlist) and declares `botocore`.
  Transcription honours `ReleaseWatcher.abort` (Transcribe wait + per-turn) → row `transcribing`,
  message redelivered.

- Photogrammetry robustness batch (resumable stages, no-cycling backstop at receive 5, mesh budget,
  photo orientation) — deployed and smoked on the 51-photo set: one attempt, 14 min, no refine above
  400 k faces, decimate to 500 k, 0 mixed-dimension errors.
- `deploy.yml`: one Deploy workflow, change detection, API → Vue/workers ordering, manual dispatch.
- Scan page: sample preload, Photos view with API-made thumbnails, mesh loading pill, toasts
  top-right, overlay ‹ › + arrow keys, per-thumbnail loading state. Pillow moved to runtime deps
  after `:83` crash-looped on it. Sample-job thumbnails were briefly written inside `images/` (44
  "photos") — fixed, S3 cleaned.
- GPU startup estimate measured from the ledger (median of RunTask → first claim), promised value
  recorded per launch, Usage panel Startups section; PR #13 (merged, deployed 23:23 Z): stage
  timings from ECS, cold/warm, per-photo match status, close scan.
- Infra: scratch volume + `maxReceiveCount` 5 applied; CORS GET; admin release endpoint; mesh
  download URLs; warnings column; both worker task-defs pinned to the deployed sha in tfvars.
- Docs: deploy runbook rewritten; private docs track (`docs/private/`, gitudl + Henry) with the
  VPC map and an ops log; gitleaks denylist for real account/resource ids in the git hooks.
