import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.sqs_publisher import MockSQSPublisher, SQSPublisher


def test_publish_photogrammetry_job_body():
    with patch("boto3.client") as client:
        pub = SQSPublisher("https://sqs.test/q", "us-east-1")
        job_id = uuid4()
        pub.publish_photogrammetry_job(job_id)
    kw = client.return_value.send_message.call_args.kwargs
    assert kw["QueueUrl"] == "https://sqs.test/q"
    assert json.loads(kw["MessageBody"]) == {"type": "photogrammetry_job", "job_id": str(job_id)}


def test_mock_has_the_method():
    MockSQSPublisher().publish_photogrammetry_job(uuid4())
