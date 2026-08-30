FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

RUN apt-get update && apt-get install -y python3.12 python3.12-venv libpython3.12 ffmpeg git curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create venv and use it for all subsequent pip/python calls
RUN python3.12 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY gpu-worker/ /app/gpu-worker/
# constraints.txt pins every package (torch included) to the acceptance-tested image; see the header there.
COPY transcription-worker/constraints.txt /app/constraints.txt
RUN pip install --no-cache-dir -c /app/constraints.txt /app/gpu-worker
COPY transcription-worker/pyproject.toml .

ARG HUGGINGFACE_TOKEN

# pyannote 4.x pins torch/torchcodec/torchaudio — install first so its versions win
RUN pip install --no-cache-dir -c /app/constraints.txt "pyannote.audio==4.0.4"
# speechbrain pinned: an unpinned rebuild picked up 1.1.1 (from_hparams API change) and broke prod, 2026-08-28.
RUN pip install --no-cache-dir -c /app/constraints.txt "speechbrain==1.1.1" pydub boto3 pydantic-settings pgvector asyncpg sqlalchemy psycopg2-binary scipy requests soundfile

# Pre-download pyannote model at build time (revision pinned 2026-03-06)
ENV HF_HOME=/app/hf_cache
RUN python -c "\
import torchaudio; \
torchaudio.list_audio_backends = getattr(torchaudio, 'list_audio_backends', lambda: []); \
import os; \
from pyannote.audio import Pipeline; \
Pipeline.from_pretrained(\
    'pyannote/speaker-diarization-community-1',\
    revision='3533c8cf8e369892e6b79ff1bf80f7b0286a54ee',\
    token=os.environ.get('HUGGINGFACE_TOKEN') or None,\
)"

# Pre-download SpeechBrain model at build time using snapshot_download.
# Bypasses EncoderClassifier.from_hparams so we avoid huggingface_hub API
# incompatibilities (use_auth_token removal, custom.py 404 on old revisions).
# At runtime, SPEECHBRAIN_CHECKPOINT points to the local dir so from_hparams
# reads directly from disk without any HF network calls.
RUN python -c "\
from huggingface_hub import snapshot_download;\
snapshot_download(\
    repo_id='speechbrain/spkrec-ecapa-voxceleb',\
    revision='0f99f2d0ebe89ac095bcc5903c4dd8f72b367286',\
    local_dir='/app/speechbrain_model',\
)"

COPY transcription-worker/ .
ENV SPEECHBRAIN_CACHE=/app/speechbrain_model
ENV SPEECHBRAIN_CHECKPOINT=/app/speechbrain_model
CMD ["python", "main.py"]
