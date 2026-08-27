from pathlib import Path

import boto3


class S3Client:
    def __init__(self, bucket: str, region: str, client=None):
        self.bucket = bucket
        self._c = client or boto3.client("s3", region_name=region)

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        for page in self._c.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(o["Key"] for o in page.get("Contents", []))
        return sorted(keys)

    def download(self, key: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._c.download_file(self.bucket, key, str(dest))

    def upload_file(self, path: Path, key: str, content_type: str) -> None:
        self._c.upload_file(str(path), self.bucket, key, ExtraArgs={"ContentType": content_type})
