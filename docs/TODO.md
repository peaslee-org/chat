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

## API (chat-api)

- [ ] **`POST /gpu/release` 200 means "flag written", not "worker acknowledged"** — a worker on an image
  without the watcher (any transcription image before `7d7fa01`) never reads it. Either return the
  session's `release_requested_at`/`ended_at` on a follow-up `GET /gpu/state`, or have the controller
  fall back to `StopTask` when the row is still open after N seconds.

- [ ] **Deploy the admin release endpoint** (built 2026-08-28, unpushed): migration `n4o5p6q7r8s9`
  (three nullable `gpu_sessions` columns) + `POST /gpu/release`. Ships with the API image; the
  worker side is in the *Worker image* batch below — deploy the API first (columns must exist before
  a worker polls them; the worker's reader tolerates their absence by returning None).

- [ ] **Deploy the mesh attachment download URLs** (`bc597a4`, built 2026-08-28, unpushed):
  `GET /photogrammetry/jobs/{id}/mesh` gains `download_url` / `preview_download_url`. Ships with the
  API image; deploy before the Vue batch below (the buttons no-op against an API without the fields).

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

- [ ] **Deploy the GLB / preview download buttons** (`9ba40c9`, built 2026-08-28, unpushed) — after the
  API batch above.

- [ ] Photogrammetry store: no polling cutoff for a job stuck in `pending`; sibling uploads are
  not cancelled when one fails; dropzone not keyboard-focusable; dragover flicker over children.
- [ ] Delete "✕" in `RunSidebar` / `ScanJobCard` is a span inside a button (not keyboard-operable).

## Infra (terraform)

- [ ] **Apply the audio-bucket CORS `GET` rule** (`696a203`, 2026-08-28; `transcription-prod` plan 0/1/0).
  Until it is applied the photogrammetry viewer cannot `fetch()` the GLB cross-origin and stays on
  its poster image — the 3D preview has never rendered in production; go-live acceptance only
  checked the `/mesh` API call. Standalone, no image rebuild.

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
