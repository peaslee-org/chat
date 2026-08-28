import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from pathlib import Path


class AudioStorageService:

    def __init__(self, settings):
        self.s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            config=Config(signature_version="s3v4"),
        )
        self.transcribe = boto3.client("transcribe", region_name=settings.aws_region)
        self.bucket = settings.audio_bucket_name

    def generate_presigned_upload_url(
        self,
        s3_key: str,
        ttl_seconds: int = 900,
    ) -> str:
        """Returns a pre-signed PUT URL for direct S3 upload. TTL: 15 minutes."""
        return self.s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": s3_key},
            ExpiresIn=ttl_seconds,
        )

    def generate_presigned_download_url(
        self,
        s3_key: str,
        ttl_seconds: int = 900,
        *,
        attachment_filename: str | None = None,
    ) -> str:
        """Returns a pre-signed GET URL for direct browser download.

        With `attachment_filename`, S3 answers with
        `Content-Disposition: attachment; filename="…"`, so a plain link
        saves the object under that name instead of navigating to it.
        (A cross-origin `<a download>` attribute is ignored by browsers.)
        """
        params = {"Bucket": self.bucket, "Key": s3_key}
        if attachment_filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{attachment_filename}"'
        return self.s3.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=ttl_seconds,
        )

    def object_exists(self, s3_key: str) -> bool:
        """head_object; returns False on 404."""
        try:
            self.s3.head_object(Bucket=self.bucket, Key=s3_key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def read_object_text(self, s3_key: str) -> str | None:
        """Returns the object's text content, or None if it doesn't exist."""
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=s3_key)
            return response["Body"].read().decode().strip()
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return None
            raise

    def get_object_bytes(self, s3_key: str) -> bytes:
        """Downloads S3 object into memory."""
        response = self.s3.get_object(Bucket=self.bucket, Key=s3_key)
        return response["Body"].read()

    def delete_objects(self, s3_keys: list[str]) -> None:
        """Batch delete. Silently ignores missing keys."""
        if not s3_keys:
            return
        self.s3.delete_objects(
            Bucket=self.bucket,
            Delete={"Objects": [{"Key": k} for k in s3_keys], "Quiet": True},
        )

    def list_keys_with_prefix(self, prefix: str) -> list[str]:
        """Lists all object keys with the given prefix."""
        keys: list[str] = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def start_transcription_job(
        self,
        job_id: str,
        audio_s3_key: str,
        user_id: str,
        speaker_count_hint: int | None,
        language: str,
    ) -> tuple[str, str]:
        """Starts an AWS Transcribe job. Returns (aws_job_name, transcribe_output_s3_key).

        Speaker diarization is handled by pyannote-audio in the transcription worker;
        Transcribe is used only for word-level timestamps.
        """
        aws_job_name = f"job-{job_id}"
        output_key = f"audio/{user_id}/{job_id}/transcript_raw.json"
        self.transcribe.start_transcription_job(
            TranscriptionJobName=aws_job_name,
            LanguageCode=language,
            Media={"MediaFileUri": f"s3://{self.bucket}/{audio_s3_key}"},
            OutputBucketName=self.bucket,
            OutputKey=output_key,
        )
        return aws_job_name, output_key


class MockAudioStorageService:
    """No-op S3/Transcribe implementation for local dev (USE_MOCK_TRANSCRIPTION=true).

    Upload/download URLs point to the API's own dev-upload sink so the browser
    can complete the PUT without needing real S3.
    """

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self._base_url = base_url.rstrip("/")

    def generate_presigned_upload_url(self, s3_key: str, ttl_seconds: int = 900) -> str:
        return f"{self._base_url}/api/v1/transcribe/dev-upload/{s3_key}"

    def generate_presigned_download_url(
        self, s3_key: str, ttl_seconds: int = 900, *, attachment_filename: str | None = None
    ) -> str:
        return f"{self._base_url}/api/v1/transcribe/dev-upload/{s3_key}"

    def write_object(self, s3_key: str, data: bytes) -> None:
        pass

    def object_exists(self, s3_key: str) -> bool:
        return True

    def read_object_text(self, s3_key: str) -> str | None:
        return None

    def get_object_bytes(self, s3_key: str) -> bytes:
        return b""

    def delete_objects(self, s3_keys: list[str]) -> None:
        pass

    def list_keys_with_prefix(self, prefix: str) -> list[str]:
        return []

    def start_transcription_job(
        self,
        job_id: str,
        audio_s3_key: str,
        user_id: str,
        speaker_count_hint: int | None,
        language: str,
    ) -> tuple[str, str]:
        return f"mock-job-{job_id}", f"audio/{user_id}/{job_id}/transcript_raw.json"


class LocalAudioStorageService:
    """Filesystem-backed storage for local dev (USE_MOCK_TRANSCRIPTION=true).

    Upload URLs point to the API's own dev-upload sink; the sink writes the body
    to LOCAL_STORAGE_PATH so the file is actually available for the dev worker.
    All other operations read/write from the same root directory.
    """

    def __init__(self, base_url: str, storage_path: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._root = Path(storage_path)
        self._root.mkdir(parents=True, exist_ok=True)

    def generate_presigned_upload_url(self, s3_key: str, ttl_seconds: int = 900) -> str:
        return f"{self._base_url}/api/v1/transcribe/dev-upload/{s3_key}"

    def generate_presigned_download_url(
        self, s3_key: str, ttl_seconds: int = 900, *, attachment_filename: str | None = None
    ) -> str:
        return f"{self._base_url}/api/v1/transcribe/dev-upload/{s3_key}"

    def write_object(self, s3_key: str, data: bytes) -> None:
        dest = self._root / s3_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def object_exists(self, s3_key: str) -> bool:
        return (self._root / s3_key).exists()

    def read_object_text(self, s3_key: str) -> str | None:
        p = self._root / s3_key
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8").strip()

    def get_object_bytes(self, s3_key: str) -> bytes:
        return (self._root / s3_key).read_bytes()

    def delete_objects(self, s3_keys: list[str]) -> None:
        for key in s3_keys:
            (self._root / key).unlink(missing_ok=True)

    def list_keys_with_prefix(self, prefix: str) -> list[str]:
        base = self._root / prefix
        if base.is_dir():
            return [str(p.relative_to(self._root)) for p in base.rglob("*") if p.is_file()]
        # prefix may be a path fragment (not a directory); search parent
        parent = base.parent
        stem = base.name
        if not parent.exists():
            return []
        return [
            str(p.relative_to(self._root))
            for p in parent.iterdir()
            if p.name.startswith(stem) and p.is_file()
        ]

    def start_transcription_job(
        self,
        job_id: str,
        audio_s3_key: str,
        user_id: str,
        speaker_count_hint: int | None,
        language: str,
    ) -> tuple[str, str]:
        return f"mock-job-{job_id}", f"audio/{user_id}/{job_id}/transcript_raw.json"
