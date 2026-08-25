"""Task ARN from the ECS metadata v4 endpoint; instance id from IMDSv2. None when not on ECS/EC2."""
import logging
import os

import requests

logger = logging.getLogger(__name__)
_IMDS = "http://169.254.169.254/latest"


def task_arn() -> str | None:
    base = os.environ.get("ECS_CONTAINER_METADATA_URI_V4")
    if not base:
        return None
    try:
        return requests.get(f"{base}/task", timeout=1).json().get("TaskARN")
    except Exception:
        logger.warning("ECS task metadata unavailable", exc_info=True)
        return None


def instance_id() -> str | None:
    try:
        token = requests.put(
            f"{_IMDS}/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
            timeout=1,
        ).text
        return requests.get(
            f"{_IMDS}/meta-data/instance-id",
            headers={"X-aws-ec2-metadata-token": token},
            timeout=1,
        ).text
    except Exception:
        return None
