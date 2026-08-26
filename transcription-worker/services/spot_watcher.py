import logging
import threading

import boto3
import requests

logger = logging.getLogger(__name__)

_METADATA_URL = "http://169.254.169.254/latest/meta-data/spot/termination-time"
_POLL_INTERVAL = 5  # seconds


class SpotWatcher:
    """
    Polls the EC2 instance metadata endpoint for a Spot interruption notice.
    On a 2-minute warning, immediately releases the SQS message back to the
    queue (VisibilityTimeout=0) so another instance can pick it up.

    No-op on non-EC2 environments (Fargate, local dev) — the metadata endpoint
    simply times out.
    """

    # Process-wide: set once a termination notice has been seen. WorkerLoop reads it
    # between messages and exits; the per-message release below still happens.
    interrupted = threading.Event()

    def __init__(self, queue_url: str | None, receipt_handle: str | None, region: str, *, idle: bool = False):
        self._queue_url = queue_url
        self._receipt_handle = receipt_handle
        self._idle = idle
        self._sqs = boto3.client("sqs", region_name=region) if not idle else None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    @classmethod
    def idle_watcher(cls, region: str) -> "SpotWatcher":
        """No message to release: just keeps `interrupted` current while the loop is between jobs."""
        return cls(None, None, region, idle=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(_POLL_INTERVAL):
            try:
                r = requests.get(_METADATA_URL, timeout=1)
                if r.status_code == 200:
                    logger.warning("Spot interruption notice received — releasing SQS message")
                    SpotWatcher.interrupted.set()
                    if not self._idle:
                        self._sqs.change_message_visibility(
                            QueueUrl=self._queue_url,
                            ReceiptHandle=self._receipt_handle,
                            VisibilityTimeout=0,
                        )
                    return
            except Exception:
                pass  # metadata endpoint unavailable (non-EC2 env, unit tests, etc.)
