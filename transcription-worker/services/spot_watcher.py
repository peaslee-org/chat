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

    def __init__(self, queue_url: str, receipt_handle: str, region: str):
        self._queue_url = queue_url
        self._receipt_handle = receipt_handle
        self._sqs = boto3.client("sqs", region_name=region)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

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
                    self._sqs.change_message_visibility(
                        QueueUrl=self._queue_url,
                        ReceiptHandle=self._receipt_handle,
                        VisibilityTimeout=0,
                    )
                    return
            except Exception:
                pass  # metadata endpoint unavailable (non-EC2 env, unit tests, etc.)
