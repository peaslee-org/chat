import boto3
from botocore.exceptions import ClientError

from config import Settings


class S3Client:

    def __init__(self, settings: Settings):
        self.s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        self.bucket = settings.AUDIO_BUCKET_NAME

    def download_bytes(self, s3_key: str) -> bytes:
        response = self.s3.get_object(Bucket=self.bucket, Key=s3_key)
        return response["Body"].read()

    def upload_bytes(self, s3_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.s3.put_object(Bucket=self.bucket, Key=s3_key, Body=data, ContentType=content_type)

    def upload_text(self, s3_key: str, text: str) -> None:
        self.s3.put_object(
            Bucket=self.bucket, Key=s3_key, Body=text.encode("utf-8"), ContentType="text/plain"
        )

    def delete_objects(self, s3_keys: list[str]) -> None:
        if not s3_keys:
            return
        self.s3.delete_objects(
            Bucket=self.bucket,
            Delete={"Objects": [{"Key": k} for k in s3_keys], "Quiet": True},
        )

    def list_keys_with_prefix(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys
