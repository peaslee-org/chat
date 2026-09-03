from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_db
from app.repositories.conversation import ConversationRepository
from app.repositories.photogrammetry import PhotogrammetryRepository
from app.repositories.transcription import TranscriptionRepository
from app.services.audio_storage import AudioStorageService, LocalAudioStorageService
from app.services.public_service import PublicService
from app.services.transcript_compiler import compile_defaults


def get_public_service(db: AsyncSession = Depends(get_db)) -> PublicService:
    s = get_settings()
    if s.use_mock_photogrammetry or s.use_mock_transcription:
        storage = LocalAudioStorageService(s.mock_upload_base_url, s.local_storage_path)
    else:
        storage = AudioStorageService(s)
    return PublicService(
        PhotogrammetryRepository(db),
        TranscriptionRepository(db),
        ConversationRepository(db),
        storage,
        compile_defaults(s),
    )
