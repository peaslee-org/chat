import logging

import torchaudio as _torchaudio
if not hasattr(_torchaudio, 'list_audio_backends'):
    # torchaudio >= 2.1 removed list_audio_backends(); speechbrain still calls it
    _torchaudio.list_audio_backends = lambda: []

import huggingface_hub as _hf
_orig_hf_hub_download = _hf.hf_hub_download
def _patched_hf_hub_download(*args, use_auth_token=None, **kwargs):
    # huggingface_hub >= 0.23 removed use_auth_token; speechbrain 1.x still passes it
    if use_auth_token is not None and 'token' not in kwargs:
        kwargs['token'] = use_auth_token
    return _orig_hf_hub_download(*args, **kwargs)
_hf.hf_hub_download = _patched_hf_hub_download

from config import Settings
from handlers.transcription import process_transcription_job
from handlers.embedding import process_sample_embedding
from gpu_worker.db import make_session_factory
from gpu_worker.ecs_metadata import instance_id, task_arn
from gpu_worker.session import GpuSessionStore
from gpu_worker.sqs import run_sqs_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

settings = Settings()

# Existing handlers take (body, settings); the shell passes (body, message).
HANDLERS = {
    "transcription_job": lambda body, _msg: process_transcription_job(body, settings),
    "sample_embedding": lambda body, _msg: process_sample_embedding(body, settings),
}


def run() -> None:
    logger.info("Transcription worker started (idle_exit=%ss, max_lifetime=%ss)",
                settings.IDLE_EXIT_SECONDS, settings.MAX_LIFETIME_SECONDS)
    run_sqs_worker(
        queue_url=settings.TRANSCRIBE_SQS_QUEUE_URL,
        region=settings.AWS_REGION,
        handlers=HANDLERS,
        session_store=GpuSessionStore(task_arn(), instance_id(), make_session_factory(settings.DATABASE_URL)),
        idle_exit_seconds=settings.IDLE_EXIT_SECONDS,
        max_lifetime_seconds=settings.MAX_LIFETIME_SECONDS,
        visibility_timeout=settings.SQS_VISIBILITY_TIMEOUT,
        visibility_extension_interval=settings.SQS_VISIBILITY_EXTENSION_INTERVAL,
    )


if __name__ == "__main__":
    run()
