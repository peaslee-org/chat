from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    AUDIO_BUCKET_NAME: str
    TRANSCRIBE_SQS_QUEUE_URL: str
    AWS_REGION: str = "us-east-1"
    SQS_VISIBILITY_EXTENSION_INTERVAL: int = 300  # seconds
    SQS_VISIBILITY_TIMEOUT: int = 600
    MATCHING_THRESHOLD: float = 0.25  # cosine distance
    SPEECHBRAIN_CHECKPOINT: str = "speechbrain/spkrec-ecapa-voxceleb"
    SPEECHBRAIN_REVISION: str = "3c54e95"
    SPEECHBRAIN_CACHE: str = "/app/speechbrain_model"
    HUGGINGFACE_TOKEN: str = ""
    PYANNOTE_MODEL: str = "pyannote/speaker-diarization-community-1"
    # When set, upload per-job fixture JSON files to S3 after each pipeline stage so
    # dev_worker.py can replay them locally without running ML models.
    # Value is an S3 key prefix, e.g. "dev-fixtures". Files land at
    # <prefix>/<job_id>/{transcribe,diarize,matcher}.json in AUDIO_BUCKET_NAME.
    DEV_CAPTURE_FIXTURES_S3_PREFIX: str = ""
    IDLE_EXIT_SECONDS: int = 900
    MAX_LIFETIME_SECONDS: int = 10800
