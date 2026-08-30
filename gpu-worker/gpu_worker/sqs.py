"""SQS consumption shell shared by the GPU workers.

One message at a time; a background thread extends visibility while a handler runs; a
SpotWatcher releases the in-flight message on a 2-minute interruption notice; WorkerLoop
decides when the process exits (idle, max lifetime, interruption) and keeps the gpu_sessions
ledger. Handlers receive (body, message); the message carries message["Attributes"]["ApproximateReceiveCount"]
when SQS returns it. A handler that returns acks the message; one that raises leaves it for
redelivery — including Interrupted, which the SpotWatcher has already released with VisibilityTimeout=0.
"""
import json
import logging
import threading
from typing import Callable

import boto3

from gpu_worker.loop import LoopConfig, WorkerLoop
from gpu_worker.release_watcher import ReleaseWatcher
from gpu_worker.spot_watcher import SpotWatcher

logger = logging.getLogger(__name__)

Handler = Callable[[dict, dict], None]


class Interrupted(Exception):
    """Raised by a handler that stopped early — a spot interruption notice, or an admin *immediate*
    release (`ReleaseWatcher.abort`). The message is left for redelivery, not acked."""


def receive_count(message: dict) -> int:
    """SQS's ApproximateReceiveCount for this message; 1 when the attribute is absent (tests, old shells)."""
    return int(message.get("Attributes", {}).get("ApproximateReceiveCount", 1))


def run_sqs_worker(
    *,
    queue_url: str,
    region: str,
    handlers: dict[str, Handler],
    session_store,
    idle_exit_seconds: int,
    max_lifetime_seconds: int,
    visibility_timeout: int = 600,
    visibility_extension_interval: int = 300,
    sqs_client=None,
    watcher_factory=SpotWatcher,
    idle_watcher_factory=SpotWatcher.idle_watcher,
    release_watcher_factory=ReleaseWatcher,
) -> str:
    sqs = sqs_client or boto3.client("sqs", region_name=region)
    interrupted = watcher_factory.interrupted

    def extend_visibility(receipt_handle: str, stop: threading.Event) -> None:
        while not stop.wait(visibility_extension_interval):
            try:
                sqs.change_message_visibility(
                    QueueUrl=queue_url, ReceiptHandle=receipt_handle, VisibilityTimeout=visibility_timeout
                )
            except Exception:
                logger.warning("Failed to extend message visibility", exc_info=True)

    def receive() -> list:
        return sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=20, AttributeNames=["ApproximateReceiveCount"]).get("Messages", [])

    def process(message: dict) -> None:
        body = json.loads(message["Body"])
        msg_type = body.get("type")
        handler = handlers.get(msg_type)
        receipt_handle = message["ReceiptHandle"]
        if handler is None:
            logger.error("Unknown message type %r — leaving for redelivery", msg_type)
            return
        stop = threading.Event()
        threading.Thread(target=extend_visibility, args=(receipt_handle, stop), daemon=True).start()
        watcher = watcher_factory(queue_url, receipt_handle, region)
        watcher.start()
        try:
            handler(body, message)
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
            logger.info("Message type=%s processed and deleted", msg_type)
        except Interrupted:
            logger.warning("Message type=%s interrupted — released to the queue", msg_type)
        except Exception:
            logger.error("Message type=%s failed; will retry via SQS", msg_type, exc_info=True)
        finally:
            stop.set()
            watcher.stop()

    idle_watcher = idle_watcher_factory(region)
    idle_watcher.start()
    release_watcher = release_watcher_factory(session_store)
    release_watcher.start()
    try:
        loop = WorkerLoop(
            receive=receive, process=process, sessions=session_store, interrupted=interrupted,
            released=ReleaseWatcher.released,
            config=LoopConfig(idle_exit_seconds=idle_exit_seconds, max_lifetime_seconds=max_lifetime_seconds),
        )
        return loop.run()
    finally:
        idle_watcher.stop()
        release_watcher.stop()
