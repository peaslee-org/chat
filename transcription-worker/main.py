import json
import logging
import threading

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

import boto3

from config import Settings
from handlers.transcription import process_transcription_job
from handlers.embedding import process_sample_embedding
from services.ecs_metadata import instance_id, task_arn
from services.gpu_session import GpuSessionStore
from services.spot_watcher import SpotWatcher
from worker_loop import LoopConfig, WorkerLoop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

settings = Settings()
sqs = boto3.client("sqs", region_name=settings.AWS_REGION)

HANDLERS = {
    "transcription_job": process_transcription_job,
    "sample_embedding": process_sample_embedding,
}


def extend_visibility(receipt_handle: str, stop_event: threading.Event) -> None:
    """Background thread: extends SQS message visibility every interval seconds."""
    while not stop_event.wait(settings.SQS_VISIBILITY_EXTENSION_INTERVAL):
        try:
            sqs.change_message_visibility(
                QueueUrl=settings.TRANSCRIBE_SQS_QUEUE_URL,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=settings.SQS_VISIBILITY_TIMEOUT,
            )
        except Exception:
            logger.warning("Failed to extend message visibility", exc_info=True)


def process_message(message: dict) -> None:
    body = json.loads(message["Body"])
    msg_type = body.get("type")
    handler = HANDLERS.get(msg_type)
    if not handler:
        raise ValueError(f"Unknown message type: {msg_type}")

    receipt_handle = message["ReceiptHandle"]

    stop_event = threading.Event()
    extender = threading.Thread(
        target=extend_visibility,
        args=(receipt_handle, stop_event),
        daemon=True,
    )
    extender.start()

    watcher = SpotWatcher(settings.TRANSCRIBE_SQS_QUEUE_URL, receipt_handle, settings.AWS_REGION)
    watcher.start()

    try:
        handler(body, settings)
        sqs.delete_message(
            QueueUrl=settings.TRANSCRIBE_SQS_QUEUE_URL,
            ReceiptHandle=receipt_handle,
        )
        logger.info("Message type=%s processed and deleted", msg_type)
    except Exception:
        logger.error("ERROR Message type=%s failed; will retry via SQS", msg_type, exc_info=True)
    finally:
        stop_event.set()
        watcher.stop()


def receive_messages() -> list:
    resp = sqs.receive_message(
        QueueUrl=settings.TRANSCRIBE_SQS_QUEUE_URL,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=20,
    )
    return resp.get("Messages", [])


def run() -> None:
    logger.info("Transcription worker started (idle_exit=%ss, max_lifetime=%ss)",
                settings.IDLE_EXIT_SECONDS, settings.MAX_LIFETIME_SECONDS)
    # A per-message SpotWatcher only exists while a message is in flight, so a notice that
    # arrives while idle would otherwise go unseen until the next message. This one just
    # keeps SpotWatcher.interrupted current for the whole process lifetime.
    idle_watcher = SpotWatcher.idle_watcher(settings.AWS_REGION)
    idle_watcher.start()
    try:
        loop = WorkerLoop(
            receive=receive_messages,
            process=process_message,
            sessions=GpuSessionStore(task_arn(), instance_id()),
            interrupted=SpotWatcher.interrupted,
            config=LoopConfig(
                idle_exit_seconds=settings.IDLE_EXIT_SECONDS,
                max_lifetime_seconds=settings.MAX_LIFETIME_SECONDS,
            ),
        )
        loop.run()
    finally:
        idle_watcher.stop()


if __name__ == "__main__":
    run()
