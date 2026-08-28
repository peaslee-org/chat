# Photogrammetry robustness: mesh budget, resumable stages, no OOM cycling, photo warnings

**Date:** 2026-08-28. **Status:** approved design, awaiting implementation plan.

## Why

A 51-photo, multi-object scan reached the texture stage and was then killed by the container
memory limit (exit 137, `OutOfMemoryError`) 22 s after `TextureMesh` finished — i.e. inside
`obj_to_glb`. The mesh was 631 574 vertices / 1 261 288 faces with two 8192² atlases; the cat
sample is 28 467 faces with one 1024² atlas. `RefineMesh` had doubled the face count (675 k →
1.26 M) at a 16 GB virtual peak on its own.

The row was left `processing`; the SQS visibility lapsed; the replacement worker received the
same message and — because `RESTARTABLE = ("queued", "processing")` — set `stage = "sfm"` and
started over. The UI showed "step 1" again. Left alone it would have repeated three times
(`maxReceiveCount = 3`), then parked the message in the DLQ with the row still `processing` and no
error message. Three of the 51 photos had been silently dropped by COLMAP at the start
(`CAMERA_SINGLE_DIM_ERROR`: the phone had auto-rotated them to landscape) and nothing told the
user.

Four changes, one deploy batch:

1. a **mesh budget** so the export cannot grow past what the worker and a viewer can hold;
2. **stage checkpoints on the instance disk** plus a **no-cycling rule**: a stage that crashed is
   never re-run, and a message can never reach the DLQ leaving the row `processing`;
3. **photo orientation normalisation** at fetch;
4. a **`warnings` list** on the job, surfaced in the scan view and as toasts.

ECS managed scaling's scale-out-from-zero over-launch (two instances for one task, seen on every
cold start so far) is **recorded, not changed** — decision 2026-08-28.

## Non-goals

- S3 checkpoints (a spot interruption or lost instance restarts the job from the beginning, as
  today).
- Fixing the OpenMVS seam-leveling defect, gravity alignment, per-camera groups for mixed
  cameras (`--ImageReader.single_camera_per_folder`) — all stay in `docs/TODO.md`.
- Any change to the transcription worker beyond what the shared `gpu_worker` shell gains
  (the receive-count attribute is harmless there).

## 1. Mesh budget (worker)

Two constants in `handlers/photogrammetry.py`:

```
REFINE_MAX_FACES = 400_000   # RefineMesh only below this (it roughly doubles faces, 16 GB VmPeak at 675 k)
FACE_BUDGET      = 500_000   # texture/export never see more than this
```

- `Reconstruction.mesh()` returns `(ply_path, faces)`. Faces are parsed from OpenMVS's
  `Mesh '<name>' saved: V vertices, F faces` line in the runner output of the *last* mesh tool
  that ran (`openmvs.mesh_faces(output) -> int`; `StageError("ReconstructMesh", "could not read
  face count")` if absent).
- `refine` is decided by the handler **after** `ReconstructMesh`: `refine = image_count <=
  REFINE_MAX_IMAGES and faces <= REFINE_MAX_FACES`. So `mesh()` becomes two calls:
  `reconstruct_mesh()` → faces → optional `refine_mesh()`. (Today's job: 675 k → no refine.)
- If `faces > FACE_BUDGET`: `texture_mesh(..., decimate=FACE_BUDGET / faces)` adds
  `--decimate <ratio>` (OpenMVS applies it to the input surface before texturing) and the
  handler appends the warning `Mesh simplified from 1,261,288 to about 500,000 faces to fit the
  viewer`. `--max-texture-size 8192` is unchanged.
- **Export:** `obj_to_glb` stops forcing a single mesh. It loads the OBJ as a `trimesh.Scene`,
  applies `CV_TO_GLTF` to every geometry, and exports the scene as GLB (one primitive per
  material; `<model-viewer>` renders multi-primitive glTF). This removes trimesh's
  concatenate-and-repack-textures path, which is the only code that ran between `TextureMesh ok`
  and the kill. Single-material OBJs (the cat) produce the same GLB as today apart from node
  structure; the existing texel-sampling check in `tests/test_export.py` stays green.

## 2. Checkpoints and the no-cycling rule

### Scratch on the instance

`infra/modules/photogrammetry/main.tf`: the task definition gains

```
volume { name = "scratch"; host_path = "/var/lib/photogrammetry" }
mountPoints = [{ sourceVolume = "scratch", containerPath = "/tmp/pg" }]
```

`WORK_DIR` stays `/tmp/pg`. The host path is on the instance root volume (80 GB). A replacement
task started by the API's status-poll `ensure_worker("resume")` lands on the same instance while
it is up, so the job directory is still there. An instance that is gone takes its scratch with it
— that is the S3-checkpoint non-goal.

### Markers

Inside `work = WORK_DIR/<job_id>/`:

| file | written | contents |
|---|---|---|
| `stage.started` | at the start of every stage | the stage name |
| `sfm.done` | after sfm passes the 60 % gate | `{"sparse": "<path>", "registered_images": n}` |
| `dense.done` | after dense | `{"dense": "<path>"}` |
| `mesh.done` | after mesh | `{"ply": "<path>", "faces": n}` |
| `texture.done` | after texture | `{"obj": "<path>"}` |
| `publish.done` | never — completion removes the directory | — |

`publish` is the export + upload + `complete` write. It has no DB stage of its own (the UI's
strip is sfm/dense/mesh/texture; the row stays at `texture`), but it gets `stage.started =
publish` like any other stage so a crash in `obj_to_glb` — today's case — is caught by rule 2.
The user-facing name for it is "export".

`stage.started` is removed when the stage's `.done` is written, and on the `Interrupted` path
(spot interruption / admin release), so a stage that was *stopped* is never mistaken for one that
*crashed*.

`Checkpoints(work)` in `pipeline/checkpoints.py` owns these files: `started(stage)`,
`done(stage, **data)`, `completed(stage) -> dict | None`, `crashed_stage() -> str | None`,
`clear_started()`. The handler reads as a stage table with a `if not ck.completed("dense"):`
guard around each stage.

### Rules at message receipt

The handler runs, in order, before any stage:

1. Row missing or status not in `RESTARTABLE` → skip and ack (unchanged).
2. `crashed_stage()` is set (a `stage.started` with no matching `.done`) → the previous attempt
   died inside that stage without a handshake. **Fail now, do not run anything:**
   `status = failed`, `stage = None`, `error_message = "Reconstruction crashed during the
   <stage> stage (probably out of memory) — try fewer photos or one object per scan."` Log at
   ERROR. Ack. Scratch removed.
3. `ApproximateReceiveCount > MAX_ATTEMPTS (3)` → same failure with `"… crashed repeatedly …"`.
   This is the backstop for the no-scratch case (instance replaced) and guarantees a message
   never ages out to the DLQ with the row still `processing`. The SQS shell requests the
   attribute (`AttributeNames=["ApproximateReceiveCount"]`) and the handler reads it from the
   message it already receives.
4. Otherwise resume: each stage whose `.done` exists is skipped and its recorded outputs reused;
   the DB `stage` is set to the first stage actually run.

The row's `status` is set to `processing` and `stage` to the resumed stage on receipt, as today.

### Cleanup

- `rmtree(work)` on **complete** and on **failed** (both branches of rule 2/3 included).
- **Not** removed on `Interrupted` (spot/release: the same instance may get the job back) nor on
  the transient-S3 re-raise path (unchanged: redelivery restarts fetch; fetch is idempotent and
  overwrites).
- At worker start, `sweep_stale(WORK_DIR, max_age=24h)` deletes job directories whose newest
  mtime is older than a day (an instance rarely lives that long; belt and braces).

### What still restarts from the beginning

Spot interruption or an instance lost outright: no markers survive; the first receipt on a new
instance runs the full pipeline (rule 4 with no `.done` files). Rule 3 caps that at three
receipts total.

## 3. Photo orientation (worker)

`pipeline/photos.py: normalise(images_dir) -> PhotoReport` runs after download, before COLMAP:

1. Open each file with PIL, `ImageOps.exif_transpose`, note `(w, h)`. Files whose orientation
   changed under the transpose are re-saved (JPEG quality 95; PNG as-is) so COLMAP sees the
   upright pixels — COLMAP reads raw bitmaps and ignores EXIF orientation.
2. Majority orientation = the `(w, h)` seen most often. Every photo whose size is the
   **transpose** of the majority is rotated 90° (clockwise; the direction is immaterial to SfM)
   and re-saved. Same lens, same focal, centred principal point → `--ImageReader.single_camera 1`
   stays valid. Warning: `3 photos were rotated to match the others (phone auto-rotate)`.
3. Photos whose size matches neither are moved out of `images/` to `work/skipped/` and reported:
   `2 photos have a different resolution and were skipped: IMG_0049.jpg, IMG_0050.jpg`.
4. `PhotoReport(usable: int, rotated: list[str], skipped: list[str])`. The 60 % registration gate
   uses `usable`; the `image_count` column is untouched (it is what the user uploaded).

If `usable < MIN_IMAGES (5)` after skipping, fail with `Only N photos could be used …` (a
`StageError("fetch", …)`).

## 4. Warnings, end to end

- **DB:** `photogrammetry_jobs.warnings JSONB NULL` — alembic migration in `chat-api`
  (`o5p6q7r8s9t0_add_photogrammetry_warnings`), mirrored in the worker's `models.py`
  (`Mapped[Optional[list]]`, `JSONB`). Stored as a JSON array of strings; `NULL` and `[]` are
  equivalent.
- **Worker:** the handler keeps `warnings: list[str]` and calls `_update(job_id,
  warnings=list(warnings))` every time it appends, so a warning is visible in the UI while the job
  is still running. On a fresh start (no `.done` files) the list begins empty; on a resume the
  handler seeds it from the row, and `append` ignores a string already present — fetch always
  re-runs, so its rotation/skip warnings would otherwise repeat.
- **API:** `JobStatusResponse.warnings: list[str] = []` (`_to_response` maps `NULL → []`).
- **Vue:**
  - `PhotogrammetryJob.warnings: string[]` in `types`.
  - `ScanDetailView`: a yellow notice block (`border-amber-200 bg-amber-50 text-amber-800`)
    listing each warning, shown for any status once `warnings.length > 0`.
  - `ScanJobCard`: a `⚠` glyph before the badge when `warnings.length > 0`, `title` = the
    warnings joined.
  - Store: the poll `tick` compares `updated.warnings.length` with the cached job's and
    `pushToast("\"<name>\": <warning>")` for each new one. The existing `failed` toast stays; a
    `complete` toast is **not** added (not asked for).

## 5. Scaling — record only

Scale-out from zero launches two instances for one pending task (ECS managed scaling with the
Auto Scaling group at zero; the step-size limits do not govern that case). Observed on every cold
start to date. Decision: leave `gpu_max_size` and the capacity provider as they are; note the
event in the infrastructure inventory. Revisit only if it starts costing real money.

## Deploy order (one batch)

1. **API** image with the migration and the `warnings` field — columns must exist before a worker
   writes them.
2. **Terraform:** the task-definition volume/mount (module change → overlay plan/apply; registers
   a new revision).
3. **Worker** image via CI; smoke = the sample job **and** a re-run of the 51-photo set (expect:
   3 rotation warnings, no refine, decimation warning if > 500 k, complete). Then the AMI bake and
   the task-def/AMI pins.
4. **Vue** deploy.

The worker's new code is backwards-compatible with the old task definition (no volume → scratch
is container-local, markers simply never survive a kill; rule 3 still stops the cycling).

## Testing

- `tests/test_checkpoints.py`: marker round-trips; `crashed_stage()` semantics; `clear_started()`.
- `tests/test_handler.py`: resume skips completed stages and reuses recorded outputs; a
  `stage.started` without `.done` fails without calling any stage; receive count 4 fails;
  `Interrupted` clears `stage.started` and keeps scratch; complete/failed remove scratch; warnings
  are written as they arise and cleared on a fresh start; refine gated on faces; decimate ratio
  passed when over budget.
- `tests/test_openmvs.py`: `mesh_faces()` parsing; `--decimate` argv.
- `tests/test_photos.py`: synthetic JPEGs (portrait majority + 2 landscape + 1 odd size) →
  rotated/skipped lists, files rewritten with matching dimensions, EXIF orientation honoured.
- `tests/test_export.py`: multi-material OBJ → GLB with two primitives, both textures present,
  rotation applied; existing single-material texel check unchanged.
- `gpu-worker/tests/test_sqs.py`: `receive_message` requests `ApproximateReceiveCount`.
- `chat-api`: migration up/down; `JobStatusResponse.warnings` defaults to `[]`.
- `chat-vue`: `vue-tsc` + `vite build`.
- The 1.26 M-face export cannot be reproduced on the development machine (7 GB RAM); the smoke
  bed's small textured OBJ covers the export path, and the live re-run of the 51-photo set is the
  acceptance test.
