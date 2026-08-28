"""One photogrammetry job: fetch → sfm → dense → mesh → texture → publish.

Resumable: every stage leaves a `<stage>.done` marker in the job's scratch directory (a host-path
volume — see infra) and a restarted job skips what is already done. A stage that was *started*
and never finished means the previous attempt died inside it (OOM, kill) — the job fails at once
rather than running the same stage into the same wall (spec §2). Failure mapping otherwise as
before: StageError/JobTimeout/any Exception → row `failed`, return normally (the SQS shell acks).
Interrupted → row back to `queued`, re-raise (not acked; the SpotWatcher already released the
message). Transient S3 → row left `processing`, re-raise (redelivery re-runs fetch).
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

from botocore.exceptions import BotoCoreError, ClientError

from gpu_worker.sqs import Interrupted
from models import PhotogrammetryJob
from pipeline.checkpoints import Checkpoints
from pipeline.colmap import SparseModel
from pipeline.export import make_preview, obj_to_glb
from pipeline.photos import normalise
from pipeline.runner import StageError

logger = logging.getLogger(__name__)

RESTARTABLE = ("queued", "processing")
REGISTRATION_MIN_FRACTION = 0.6
REFINE_MAX_IMAGES = 100
REFINE_MAX_FACES = 400_000   # RefineMesh roughly doubles faces at a ~16 GB virtual peak on 675 k
FACE_BUDGET = 500_000        # texture/export never see more than this
MAX_ATTEMPTS = 3             # SQS receives; matches the queue's maxReceiveCount
MIN_IMAGES = 5
ERROR_MAX_CHARS = 1000
_STAGE_NAMES = {"publish": "export"}


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


def _crash_message(stage: str | None) -> str:
    if stage is None:
        return "Reconstruction crashed repeatedly (probably out of memory) — try fewer photos or one object per scan."
    return (f"Reconstruction crashed during the {_STAGE_NAMES.get(stage, stage)} stage (probably out of memory)"
            " — try fewer photos or one object per scan.")


class _Warnings:
    """Job warnings, written to the row on every append; a string is never added twice."""
    def __init__(self, deps: Deps, job_id: uuid.UUID, existing: list[str] | None):
        self._deps, self._job_id, self._items = deps, job_id, list(existing or [])

    def add(self, *messages: str) -> None:
        new = [m for m in messages if m not in self._items]
        if not new:
            return
        self._items.extend(new)
        _update(self._deps, self._job_id, warnings=list(self._items))


def process_photogrammetry_job(body: dict, deps: Deps, receive_count: int = 1) -> None:
    job_id = uuid.UUID(body["job_id"])
    work = deps.work_root / str(job_id)
    ck = Checkpoints(work)

    with deps.session_factory() as s:
        job = s.get(PhotogrammetryJob, job_id)
        if job is None or job.status not in RESTARTABLE:
            logger.info("Job %s skipped (status=%s)", job_id, getattr(job, "status", None))
            return
        user_id, input_prefix, image_count = job.user_id, job.input_prefix, job.image_count
        resuming = ck.first_incomplete() != "sfm"      # markers, not status: a queued (interrupted) job resumes too
        crashed = ck.crashed_stage()
        if crashed is not None or receive_count > MAX_ATTEMPTS:
            reason = _crash_message(crashed)             # None → the "repeatedly" wording
            logger.error("Job %s failed before running: %s (receive_count=%d)", job_id, reason, receive_count)
            job.status, job.stage, job.error_message = "failed", None, reason
            shutil.rmtree(work, ignore_errors=True)
            return
        first_stage = ck.first_incomplete()
        job.status, job.error_message = "processing", None
        job.stage = "texture" if first_stage == "publish" else first_stage
        if not resuming:
            job.warnings = []
        warnings = _Warnings(deps, job_id, job.warnings)

    images = work / "images"
    output_prefix = f"photogrammetry/{user_id}/{job_id}/output/"
    try:
        work.mkdir(parents=True, exist_ok=True)      # exists from here on, even if fetch raises
        # ── fetch (always) ────────────────────────────────────────────────
        # S3 "folders" are placeholder zero-byte objects with a trailing "/" — not photos.
        keys = [key for key in deps.s3.list_keys(input_prefix) if not key.endswith("/")]
        if len(keys) < image_count:
            raise StageError("fetch", f"{len(keys)} of {image_count} photos found in storage")
        for key in keys:
            deps.s3.download(key, images / key.rsplit("/", 1)[-1])
        report = normalise(images, work / "skipped")
        warnings.add(*report.warnings())
        if report.usable < MIN_IMAGES:
            raise StageError("fetch", f"Only {report.usable} photos could be used — at least {MIN_IMAGES} are needed")

        recon = deps.reconstruction_factory(work, deps.clock() + deps.job_timeout_seconds)

        # ── sfm ───────────────────────────────────────────────────────────
        done = ck.completed("sfm")
        if done is None:
            ck.started("sfm")
            model = recon.sfm(images)
            needed = math.ceil(REGISTRATION_MIN_FRACTION * report.usable)
            if model.registered_images < needed:
                raise StageError("colmap mapper",
                                 f"Only {model.registered_images} of {report.usable} photos could be matched — add overlap and try again")
            ck.done("sfm", sparse=str(model.path), registered_images=model.registered_images)
            done = ck.completed("sfm")
        model = SparseModel(Path(done["sparse"]), done["registered_images"])

        # ── dense ─────────────────────────────────────────────────────────
        done = ck.completed("dense")
        if done is None:
            _update(deps, job_id, stage="dense"); ck.started("dense")
            dense = recon.dense(images, model)
            ck.done("dense", dense=str(dense)); done = ck.completed("dense")
        dense = Path(done["dense"])

        # ── mesh (reconstruct, optionally refine) ─────────────────────────
        done = ck.completed("mesh")
        if done is None:
            _update(deps, job_id, stage="mesh"); ck.started("mesh")
            ply, faces = recon.reconstruct_mesh(dense)
            if image_count <= REFINE_MAX_IMAGES and faces <= REFINE_MAX_FACES:
                ply, faces = recon.refine_mesh(dense, ply)
            ck.done("mesh", ply=str(ply), faces=faces); done = ck.completed("mesh")
        mesh_ply, faces = Path(done["ply"]), int(done["faces"])

        # ── texture ───────────────────────────────────────────────────────
        done = ck.completed("texture")
        if done is None:
            _update(deps, job_id, stage="texture"); ck.started("texture")
            decimate = None
            if faces > FACE_BUDGET:
                decimate = FACE_BUDGET / faces
                warnings.add(f"Mesh simplified from {faces:,} to about {FACE_BUDGET:,} faces to fit the viewer")
            obj = recon.texture(dense, mesh_ply, decimate=decimate)
            ck.done("texture", obj=str(obj)); done = ck.completed("texture")
        obj = Path(done["obj"])

        # ── publish (export + upload + complete) ──────────────────────────
        ck.started("publish")
        glb = obj_to_glb(obj, work / "mesh.glb")
        first_image = sorted(images.iterdir())[0]
        preview = make_preview(first_image, work / "preview.png")
        mesh_key, preview_key = output_prefix + "mesh.glb", output_prefix + "preview.png"
        deps.s3.upload_file(glb, mesh_key, "model/gltf-binary")
        deps.s3.upload_file(preview, preview_key, "image/png")
        _update(deps, job_id, status="complete", stage=None, mesh_s3_key=mesh_key, preview_s3_key=preview_key,
                completed_at=datetime.now(timezone.utc))
        logger.info("Job %s complete", job_id)
        shutil.rmtree(work, ignore_errors=True)
    except Interrupted:
        logger.warning("Job %s interrupted — back to queued", job_id)
        ck.clear_started()                       # stopped, not crashed: the next worker resumes
        _update(deps, job_id, status="queued", stage=None)
        raise
    except (ClientError, BotoCoreError):
        # Transient S3 (e.g. SlowDown) — leave the row `processing` and re-raise so the SQS
        # shell doesn't ack; redelivery re-runs fetch and resumes from the markers.
        logger.warning("Job %s hit a transient S3 error — leaving for redelivery", job_id, exc_info=True)
        ck.clear_started()
        raise
    except Exception as e:   # StageError, JobTimeout, anything else deterministic
        message = str(e)[:ERROR_MAX_CHARS] or e.__class__.__name__
        logger.error("Job %s failed: %s", job_id, message, exc_info=not isinstance(e, StageError))
        _update(deps, job_id, status="failed", stage=None, error_message=message)
        shutil.rmtree(work, ignore_errors=True)
