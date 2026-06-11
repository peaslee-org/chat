import torchaudio  # must be imported and patched before pyannote imports speechbrain
if not hasattr(torchaudio, 'list_audio_backends'):
    # torchaudio >= 2.1 removed list_audio_backends(); speechbrain still calls it
    torchaudio.list_audio_backends = lambda: []

import torch
from pyannote.audio import Pipeline

from config import Settings


class PyannoteDiarizer:
    _instance: "PyannoteDiarizer | None" = None

    @classmethod
    def get(cls) -> "PyannoteDiarizer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        settings = Settings()
        self.pipeline = Pipeline.from_pretrained(
            settings.PYANNOTE_MODEL,
            token=settings.HUGGINGFACE_TOKEN or None,
        )
        if torch.cuda.is_available():
            self.pipeline.to(torch.device("cuda"))

    def diarize(
        self,
        audio_path: str,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> dict:
        """
        Returns a dict with two keys:
          "turns"           — regular diarization; may contain overlapping segments
          "exclusive_turns" — exclusive diarization; each timestamp assigned to one speaker only
        Both are lists of {speaker_label, start, end} sorted by start time.
        """
        kwargs = {}
        if min_speakers is not None:
            kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            kwargs["max_speakers"] = max_speakers

        waveform, sample_rate = torchaudio.load(audio_path)
        audio = {"waveform": waveform, "sample_rate": sample_rate}
        output = self.pipeline(audio, **kwargs)

        def _to_turns(annotation) -> list[dict]:
            turns = []
            for turn, _, speaker in annotation.itertracks(yield_label=True):
                turns.append({
                    "speaker_label": speaker,
                    "start": turn.start,
                    "end": turn.end,
                })
            return sorted(turns, key=lambda t: t["start"])

        return {
            "turns": _to_turns(output.speaker_diarization),
        }
