import json
from uuid import UUID

import boto3


class SQSPublisher:

    def __init__(self, queue_url: str, region: str):
        self.sqs = boto3.client("sqs", region_name=region)
        self.queue_url = queue_url

    def publish_transcription_job(
        self, job_id: UUID, aws_job_name: str, speaker_ids: list[UUID] | None
    ) -> None:
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps({
                "type": "transcription_job",
                "job_id": str(job_id),
                "aws_transcribe_job_name": aws_job_name,
                "speaker_ids": [str(s) for s in speaker_ids] if speaker_ids else None,
            }),
        )

    def publish_sample_embedding(self, sample_id: UUID, s3_key: str) -> None:
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps({
                "type": "sample_embedding",
                "sample_id": str(sample_id),
                "s3_key": s3_key,
            }),
        )

    def publish_photogrammetry_job(self, job_id: UUID) -> None:
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps({"type": "photogrammetry_job", "job_id": str(job_id)}),
        )


class MockSQSPublisher:
    """No-op SQS publisher for local dev (USE_MOCK_TRANSCRIPTION=true)."""

    def publish_transcription_job(
        self, job_id: UUID, aws_job_name: str, speaker_ids: list[UUID] | None
    ) -> None:
        pass

    def publish_sample_embedding(self, sample_id: UUID, s3_key: str) -> None:
        pass

    def publish_photogrammetry_job(self, job_id: UUID) -> None:
        pass
