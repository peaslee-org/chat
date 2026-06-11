from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # App
    environment: str = "dev"
    log_level: str = "INFO"
    cors_origins: List[str] = ["*"]

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/chatapi"

    # AWS
    aws_region: str = "us-east-1"
    aws_account_id: str = ""

    # Cognito
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    cognito_region: str = "us-east-1"

    # Bedrock
    bedrock_model_id: str = "anthropic.claude-3-sonnet-20240229-v1:0"
    use_mock_bedrock: bool = False
    mock_bedrock_delay_seconds: float = 0.0

    # Audio Transcription
    audio_bucket_name: str = ""
    transcribe_sqs_queue_url: str = ""
    max_concurrent_jobs: int = 3
    use_mock_transcription: bool = False
    # Base URL of the API as seen by the browser; used to generate mock upload/download URLs
    mock_upload_base_url: str = "http://localhost:8000"
    # Seconds to wait before transitioning mock samples from processing → ready
    mock_sample_processing_delay_seconds: float = 3.0
    # Seconds to wait in each stage of a mock transcription job: transcribing → matching → complete
    mock_job_transcribing_delay_seconds: float = 5.0
    mock_job_matching_delay_seconds: float = 3.0

    # Local dev overrides — never active when environment="prod"
    dev_auth_bypass: bool = False
    dev_auth_user_sub: str = "dev-user-001"
    local_storage_path: str = "/tmp/mock-audio"
    # When true, confirm_job_upload leaves job in 'transcribing' for dev_worker.py to pick up
    # instead of spawning an in-process simulation task
    mock_worker_external: bool = False

    # Sample audio — shared S3 objects uploaded once; referenced directly (no user upload)
    sample_audio_s3_key: str = "samples/conversation.wav"
    sample_barry_s3_key: str = "samples/speakers/barry.wav"
    sample_jane_s3_key: str = "samples/speakers/jane.wav"

    # LangSmith
    langchain_tracing_v2: bool = False
    langchain_project: str = "chat-api"
    langchain_api_key: str = ""

    @property
    def cognito_jwks_url(self) -> str:
        return (
            f"https://cognito-idp.{self.cognito_region}.amazonaws.com"
            f"/{self.cognito_user_pool_id}/.well-known/jwks.json"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
