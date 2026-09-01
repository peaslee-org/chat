from app.models.conversation import Conversation
from app.models.photogrammetry import PhotogrammetryJob
from app.models.transcription import TranscriptionJob


def test_is_public_columns_exist_not_null_default_false():
    for model in (Conversation, TranscriptionJob, PhotogrammetryJob):
        col = model.__table__.c.is_public
        assert col.nullable is False, model.__name__
        assert col.server_default is not None, model.__name__
