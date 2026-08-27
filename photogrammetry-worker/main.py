import logging
from pathlib import Path

from config import Settings
from gpu_worker.db import make_session_factory
from gpu_worker.ecs_metadata import instance_id, task_arn
from gpu_worker.session import GpuSessionStore
from gpu_worker.spot_watcher import SpotWatcher
from gpu_worker.sqs import run_sqs_worker
from handlers.photogrammetry import Deps, process_photogrammetry_job
from pipeline.reconstruct import Reconstruction
from pipeline.runner import Runner
from services.s3 import S3Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

settings = Settings()


def build_deps(s: Settings) -> Deps:
    return Deps(
        session_factory=make_session_factory(s.DATABASE_URL),
        s3=S3Client(s.AUDIO_BUCKET_NAME, s.AWS_REGION),
        reconstruction_factory=lambda work, deadline: Reconstruction(
            Runner(deadline=deadline, interrupted=SpotWatcher.interrupted), work, use_gpu=bool(s.COLMAP_USE_GPU)),
        work_root=Path(s.WORK_DIR),
        use_gpu=bool(s.COLMAP_USE_GPU),
        job_timeout_seconds=s.PHOTOGRAMMETRY_JOB_TIMEOUT_SECONDS,
    )


DEPS = None
HANDLERS = {"photogrammetry_job": lambda body, _msg: process_photogrammetry_job(body, DEPS)}


def run() -> None:
    global DEPS
    DEPS = build_deps(settings)
    logger.info("Photogrammetry worker started (idle_exit=%ss, max_lifetime=%ss, job_timeout=%ss)",
                settings.IDLE_EXIT_SECONDS, settings.MAX_LIFETIME_SECONDS, settings.PHOTOGRAMMETRY_JOB_TIMEOUT_SECONDS)
    run_sqs_worker(
        queue_url=settings.PHOTOGRAMMETRY_SQS_QUEUE_URL, region=settings.AWS_REGION, handlers=HANDLERS,
        session_store=GpuSessionStore(task_arn(), instance_id(), DEPS.session_factory),
        idle_exit_seconds=settings.IDLE_EXIT_SECONDS, max_lifetime_seconds=settings.MAX_LIFETIME_SECONDS,
        visibility_timeout=settings.SQS_VISIBILITY_TIMEOUT,
        visibility_extension_interval=settings.SQS_VISIBILITY_EXTENSION_INTERVAL,
    )


if __name__ == "__main__":
    run()
