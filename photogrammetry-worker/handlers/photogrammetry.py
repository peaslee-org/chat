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

from botocore.exceptions import BotoCoreError, ClientError

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
        # S3 "folders" are placeholder zero-byte objects with a trailing "/" — not photos.
        keys = [key for key in deps.s3.list_keys(input_prefix) if not key.endswith("/")]
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
    except (ClientError, BotoCoreError):
        # Transient S3 (e.g. SlowDown) — leave the row `processing` and re-raise so the SQS
        # shell doesn't ack; redelivery restarts the job from the load step.
        logger.warning("Job %s hit a transient S3 error — leaving for redelivery", job_id, exc_info=True)
        raise
    except Exception as e:   # StageError, JobTimeout, anything else deterministic
        message = str(e)[:ERROR_MAX_CHARS] or e.__class__.__name__
        logger.error("Job %s failed: %s", job_id, message, exc_info=not isinstance(e, StageError))
        _update(deps, job_id, status="failed", stage=None, error_message=message)
    finally:
        shutil.rmtree(work, ignore_errors=True)
