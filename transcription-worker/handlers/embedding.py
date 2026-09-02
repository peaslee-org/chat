import logging
import uuid

from db import get_session
from models import SpeakerSample
from services.embedder import EcapaTdnnEmbedder
from services.s3_client import S3Client
from config import Settings

logger = logging.getLogger(__name__)


def process_sample_embedding(body: dict, settings: Settings) -> None:
    sample_id = uuid.UUID(body["sample_id"])
    s3_key = body["s3_key"]

    with get_session() as session:
        sample = session.get(SpeakerSample, sample_id)
        if sample is None:
            raise ValueError(f"Sample {sample_id} not found in DB")
        if sample.status == "ready":
            # The transcription handler can embed a sample inline (ahead of this message) when
            # matching would otherwise race a still-`processing` sample of a filtered speaker —
            # see handlers/transcription.py. This message is then a harmless duplicate.
            logger.info("Sample %s already ready — skipping (embedded inline during job matching)", sample_id)
            return

    s3 = S3Client(settings)
    embedder = EcapaTdnnEmbedder.get()

    try:
        # Step 1: Download sample audio
        audio_bytes = s3.download_bytes(s3_key)

        # Step 2: Generate embedding
        embedding = embedder.encode(audio_bytes)

        # Step 3: Update DB
        with get_session() as session:
            sample = session.get(SpeakerSample, sample_id)
            if sample is None:
                raise ValueError(f"Sample {sample_id} not found in DB")
            sample.embedding = embedding
            sample.status = "ready"

        logger.info("Sample %s embedding generated successfully", sample_id)

    except Exception as exc:
        logger.error("ERROR Sample %s embedding failed: %s", sample_id, exc)
        with get_session() as session:
            sample = session.get(SpeakerSample, sample_id)
            if sample:
                sample.status = "failed"
                sample.error_message = str(exc)
        raise
