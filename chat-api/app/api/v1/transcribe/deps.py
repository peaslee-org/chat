from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.gpu.deps import get_gpu_controller
from app.config import get_settings
from app.dependencies import get_db
from app.repositories.transcription import TranscriptionRepository
from app.services.audio_storage import AudioStorageService, LocalAudioStorageService, MockAudioStorageService
from app.services.gpu_controller import GpuController
from app.services.sqs_publisher import MockSQSPublisher, SQSPublisher
from app.services.transcription_service import LocalTranscriptionService, TranscriptionService

_mock_sqs = MockSQSPublisher()


def get_transcription_service(
    db: AsyncSession = Depends(get_db),
    gpu: GpuController | None = Depends(get_gpu_controller),
) -> TranscriptionService | LocalTranscriptionService:
    settings = get_settings()
    repo = TranscriptionRepository(db)
    if settings.use_mock_transcription:
        storage = LocalAudioStorageService(settings.mock_upload_base_url, settings.local_storage_path)
        return LocalTranscriptionService(repo, storage, _mock_sqs, settings, gpu)
    storage = AudioStorageService(settings)
    sqs = SQSPublisher(settings.transcribe_sqs_queue_url, settings.aws_region)
    return TranscriptionService(repo, storage, sqs, settings, gpu)
