# TODO / backlog

Grouped by **what a change forces you to rebuild or redeploy**, so items can be batched. Each
worker-image item costs an ECR push + task-def revision + AMI re-bake (`scripts/deploy/build-gpu-ami.sh`);
each API item an ECS deploy; Vue items a CloudFront deploy; infra items a Terraform apply.

## Worker image (batch these — rebake the GPU AMI once)

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

- [ ] `repositories/transcription.py` `list_jobs` / `list_speakers`: keyset cursor is built from
  the popped overflow row, so page 2 skips one item. Fixed in `repositories/photogrammetry.py`
  (cursor from the last *returned* row); port the fix + test.
- [ ] `pending` photogrammetry jobs never expire and count against `MAX_CONCURRENT_JOBS`
  (presigned PUTs live 15 min). Exclude `pending` older than the URL TTL from
  `count_active_jobs`, or sweep. Same precedent in transcribe.
- [ ] Malformed `cursor` → 500 (both repositories); return 422.
- [ ] Mock walk (`LocalPhotogrammetryService`) has no `failed` transition; a mid-walk exception
  leaves the job `processing` (transcribe mock does the same).

## Vue (chat-vue)

- [ ] Photogrammetry store: no polling cutoff for a job stuck in `pending`; sibling uploads are
  not cancelled when one fails; dropzone not keyboard-focusable; dragover flicker over children.
- [ ] Delete "✕" in `RunSidebar` / `ScanJobCard` is a span inside a button (not keyboard-operable).

## Infra (terraform)

- [ ] **ECS managed scaling launches 2 instances for 1 task** from zero (observed 2026-08-26 and
  2026-08-27); the spare idles ~10 min until scale-in. Check the capacity provider's
  `minimum_scaling_step_size` / target and the estimate with mixed instance types.
- [ ] **~15 min scale-in lag after the worker exits** (ECS managed scale-in = 15 low datapoints;
  observed 2026-08-27: exit 11:16 → ASG 0 at 11:32). Options: worker terminates its own
  instance on exit (`ec2:TerminateInstances` scoped by tag, `InstanceInitiatedShutdownBehavior`),
  or a custom scale-in alarm on `CapacityProviderReservation` with fewer datapoints.
- [ ] `gpu_on_demand_percentage` back to 0 once spot placement scores recover.
- [ ] Photogrammetry: `gpu_max_size` 2 is exactly the raised G/VT quota (2 × g4dn.xlarge = 8 vCPU);
  a third family needs a quota case.

## Local dev

- [ ] `chat-api/docker-compose.yml` uses `postgres:16-alpine`, which lacks pgvector — a clean
  `docker compose up` + `alembic upgrade head` fails on the speaker-embedding migration. Switch
  to `pgvector/pgvector:pg16`.
- [ ] Presigned PUT TTL (15 min) is tight for 150 photos on a slow link; consider 30–60 min for
  the PUT side only.
