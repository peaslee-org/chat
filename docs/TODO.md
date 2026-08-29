# TODO / backlog

Grouped by **what a change forces you to rebuild or redeploy**, so items can be batched. Each
worker-image item costs an ECR push + task-def revision + AMI re-bake (`scripts/deploy/build-gpu-ami.sh`);
each API item an ECS deploy; Vue items a CloudFront deploy; infra items a Terraform apply.

## Worker image (batch these — rebake the GPU AMI once)

- [ ] **Audit unpinned dependencies in both worker Dockerfiles** (`speechbrain` bit on 2026-08-28;
  `pydub boto3 pydantic-settings pgvector … soundfile` and the photogrammetry `pip install` line are
  still unpinned) — a rebuild must reproduce the image that passed acceptance.
- [ ] **Transcription job path should honour `ReleaseWatcher.abort`** (immediate release aborts only the
  photogrammetry runner today).
- [x] ~~Photogrammetry robustness (spec 2026-08-28)~~ deployed 2026-08-29 and **smoked**: sample
  (100 s) and the 51-photo set (14 min, one attempt — 681 k faces → refine skipped → `--decimate
  0.734` → 500 k textured; 0 mixed-dimension errors after orientation normalisation; VmPeak 8.2 GB).
  Remaining: **bake** the AMI with the `9fd89e1` images (current task-defs `:14` / `:59`) + pins.
- [ ] **Exported GLB is too large** — the 51-photo set produced a **45 MB** `mesh.glb` (500 k faces
  + two 8192² atlases embedded uncropped since `cfd539c` stopped re-packing; the sample went
  889 KB → 3.3 MB for the same reason). Crop each atlas to its used patches (or `--max-texture-size`
  in TextureMesh), and consider Draco / quantised attributes. Viewer loads it, but slowly.

- [x] ~~Rebake the GPU AMI with photogrammetry image `8f81e78`~~ done 2026-08-28: LT v5, task-def `:11`. (Was: task family `:10`, built by CI
  2026-08-28 14:52 Z; carries `27a23f1` y-up + `b301e89` seam leveling off). The sample scan re-run at
  15:04 Z on `:10` completed (COLMAP → Densify → Reconstruct → Refine → Texture, 90 s on an A10G;
  `mesh.glb` 889 KB) — that run is the smoke for this image. Until the rebake every cold start pulls
  the image (~5½ min on top of the ~5 min instance start).) **Bake script gotcha:** the AMI name is
  `gpu-<env>-<date>-<first image tag>`, so a same-day rebake with the same first image fails at
  `CreateImage` (`InvalidAMIName.Duplicate`) *after* the pull. Fixed in `40b6228`: names carry the UTC
  `HHMM`, and the script refuses an existing name before launching; `BAKE_MARKET` is validated.

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

- [ ] **Release watcher in both worker images** (`gpu-worker` package, built 2026-08-28, unpushed):
  graceful release works for transcription and photogrammetry; *immediate* only aborts the
  photogrammetry runner — make the transcription job path poll `ReleaseWatcher.abort` too.

- [ ] **GPU idle-release countdown that survives polling.** Today `warm_until` is only in the
  *Warm* response; the 30 s `/gpu/state` poll returns `null`, so the bar's `idle-out in mm:ss`
  vanishes, and a job-launched worker never has one. Real release time is
  `max(last_work + IDLE_EXIT_SECONDS, warm_until)` (`worker_loop.py`), known only to the worker.
  Plan: add `gpu_sessions.idle_release_at`; worker writes it on every loop pass where it already
  heartbeats; `GpuController.get_state()` returns `max(idle_release_at, warm_until)` as
  `warm_until`; bar keeps the label across polls and adds a hover title with the absolute time,
  "not known yet" while `starting`. Touches: worker `services/gpu_session.py`, `worker_loop.py`,
  `models.py`; API migration + `gpu_controller.py` + `repositories/gpu.py`; `GpuStatusBar.vue`.
- [ ] Headless mesh-render `preview.png` (pyrender + EGL) — replaces the first-photo preview
  (worker spec decision 4).
- [ ] Mixed cameras: `--ImageReader.single_camera_per_folder` with one folder per pixel size
  instead of skipping.

## API (chat-api)

- [x] ~~Photogrammetry `warnings` column + field (migration `o5p6q7r8s9t0`).~~ Deployed 2026-08-29 (`chat-api-prod:81`).

- [ ] **`POST /gpu/release` 200 means "flag written", not "worker acknowledged"** — a worker on an image
  without the watcher (any transcription image before `7d7fa01`) never reads it. Either return the
  session's `release_requested_at`/`ended_at` on a follow-up `GET /gpu/state`, or have the controller
  fall back to `StopTask` when the row is still open after N seconds.

- [x] ~~Deploy the admin release endpoint~~ live since 2026-08-28 (`chat-api-prod:80`): migration `n4o5p6q7r8s9` + `POST /gpu/release`.

- [x] ~~Deploy the mesh attachment download URLs~~ (`bc597a4`) live since 2026-08-28 (`chat-api-prod:80`).

- [ ] Photogrammetry worker: `except (ClientError, BotoCoreError): raise` in the download block retries *every* S3
  error via SQS — a permanent one (`AccessDenied`, `NoSuchKey`) spins 3× to the DLQ and leaves the row
  `processing` with no user-visible failure. Allowlist transient codes (`SlowDown`, `Throttling*`,
  `RequestTimeout`) for re-raise; fail the row for the rest. Also declare `botocore` in
  `photogrammetry-worker/pyproject.toml` (imported directly, only transitively pinned today).
- [ ] `repositories/transcription.py` `list_jobs` / `list_speakers`: keyset cursor is built from
  the popped overflow row, so page 2 skips one item. Fixed in `repositories/photogrammetry.py`
  (cursor from the last *returned* row); port the fix + test.
- [ ] `pending` photogrammetry jobs never expire and count against `MAX_CONCURRENT_JOBS`
  (presigned PUTs live 15 min). Exclude `pending` older than the URL TTL from
  `count_active_jobs`, or sweep. Same precedent in transcribe.
- [ ] Malformed `cursor` → 500 (both repositories); return 422.
- [ ] Mock walk (`LocalPhotogrammetryService`) has no `failed` transition; a mid-walk exception
  leaves the job `processing` (transcribe mock does the same).
- [ ] Photogrammetry rows outlive their S3 objects (30-day lifecycle on `photogrammetry/`): mark
  rows `expired` (or split the output prefix — a contract change) so the viewer doesn't get a 404.

## Vue (chat-vue)

- [ ] **Transcribe "Try the sample" is silently a no-op while a sample job is pending** (2026-08-28:
  clicking it did not POST; deleting the stuck job first did). Either disable the button with a hint or
  let it create a new job.

- [x] ~~Deploy the GLB / preview download buttons~~ (`9ba40c9`) live since 2026-08-28.

- [x] ~~Warnings on the scan view, ⚠ on the card, toasts for new warnings.~~ Deployed 2026-08-29.

- [ ] Photogrammetry store: no polling cutoff for a job stuck in `pending`; sibling uploads are
  not cancelled when one fails; dropzone not keyboard-focusable; dragover flicker over children.
- [ ] Delete "✕" in `RunSidebar` / `ScanJobCard` is a span inside a button (not keyboard-operable).
- [ ] `npm run type-check` and the `vue-tsc` step of `npm run build` check nothing — the root
  `tsconfig.json` is solution-style (`files: []`) and neither passes `-p tsconfig.app.json`/`-b`.
  Make the script `vue-tsc -p tsconfig.app.json --noEmit` (four pre-existing errors in
  `transcribe/*.vue` will surface).

## Infra (terraform)

- [x] ~~Apply the audio-bucket CORS `GET` rule~~ (`696a203`) — applied 2026-08-28; the 3D viewer renders in production.

- [x] ~~photogrammetry task-def: host-path scratch volume; `maxReceiveCount` 3 → 5~~ applied
  2026-08-29 (task-def `:13`; both worker `image_tag`s pinned to the deployed sha in tfvars).

- [ ] **ECS managed scaling launches 2 instances for 1 task** from zero (observed 2026-08-26 and
  2026-08-27); the spare idles ~10 min until scale-in. Check the capacity provider's
  `minimum_scaling_step_size` / target and the estimate with mixed instance types.
- [ ] **~15 min scale-in lag after the worker exits** (ECS managed scale-in = 15 low datapoints;
  observed 2026-08-27: exit 11:16 → ASG 0 at 11:32). Options: worker terminates its own
  instance on exit (`ec2:TerminateInstances` scoped by tag, `InstanceInitiatedShutdownBehavior`),
  or a custom scale-in alarm on `CapacityProviderReservation` with fewer datapoints.
- [ ] `gpu_on_demand_percentage` back to 0 once spot placement scores recover.
- [ ] **`scripts/deploy/migrate.sh` is dead**: it execs `uv run alembic …`, but the runtime stage of
  `chat-api/Dockerfile` never copies `uv` (`exec: "uv": executable file not found in $PATH`,
  2026-08-27). Migrations actually run from `scripts/entrypoint.sh` at container start, before
  gunicorn binds — so there is no deploy→migrate window and the script is only needed for a
  manual re-run. Fix: `CMD="/app/.venv/bin/python -m alembic -c /app/app/db/alembic.ini upgrade head"`,
  and say in the header that the entrypoint already does this. No deploy surface (script only).
- [ ] Photogrammetry: `gpu_max_size` 2 — two g4dn.xlarge is exactly the account's current
  On-Demand G/VT quota; a third family needs a quota increase.

## Local dev

- [ ] `chat-api/docker-compose.yml` uses `postgres:16-alpine`, which lacks pgvector — a clean
  `docker compose up` + `alembic upgrade head` fails on the speaker-embedding migration. Switch
  to `pgvector/pgvector:pg16`.
- [ ] Presigned PUT TTL (15 min) is tight for 150 photos on a slow link; consider 30–60 min for
  the PUT side only.
