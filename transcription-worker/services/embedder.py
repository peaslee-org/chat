import io
import math
import tempfile
import os

import torch
import torchaudio
from speechbrain.pretrained import EncoderClassifier

from config import Settings


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        return vector
    return [x / norm for x in vector]


class EcapaTdnnEmbedder:
    _instance: "EcapaTdnnEmbedder | None" = None

    @classmethod
    def get(cls) -> "EcapaTdnnEmbedder":
        """Singleton — model loaded once at worker startup."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        settings = Settings()
        # SPEECHBRAIN_CHECKPOINT is the snapshot the Dockerfile downloads at build time (revision
        # pinned there), so no revision= here: speechbrain >= 1.1 forwards unknown kwargs to
        # Pretrained.__init__ and every job failed with a TypeError (prod, 2026-08-28).
        self.model = EncoderClassifier.from_hparams(
            source=settings.SPEECHBRAIN_CHECKPOINT,
            savedir=settings.SPEECHBRAIN_CACHE,
        )

    def encode_tensor(self, waveform: torch.Tensor, sample_rate: int) -> list[float] | None:
        """Embed a pre-loaded waveform tensor. Returns a 192-dim L2-normalised vector, or None if the
        segment is too short for the ECAPA-TDNN model (requires >= 200ms at 16 kHz)."""
        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            waveform = resampler(waveform)
        # Average channels to mono: (channels, time) → (1, time)
        if waveform.dim() == 2:
            waveform = waveform.mean(dim=0, keepdim=True)
        # ECAPA-TDNN has CNN layers with padding=4; the mel-filterbank output needs > 4 frames,
        # which requires at least ~200 ms of audio at 16 kHz.
        if waveform.shape[-1] < 3200:
            return None
        with torch.no_grad():
            embedding = self.model.encode_batch(waveform)
        vector = embedding.squeeze().tolist()
        if isinstance(vector, float):
            vector = [vector]
        return _l2_normalize(vector)

    def encode(self, wav_bytes: bytes) -> list[float]:
        """Embed raw audio bytes. Returns a 192-dim L2-normalised vector."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(wav_bytes)
            tmp_path = tmp.name
        try:
            waveform, sample_rate = torchaudio.load(tmp_path)
            return self.encode_tensor(waveform, sample_rate)
        finally:
            os.unlink(tmp_path)
