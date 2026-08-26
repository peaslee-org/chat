# Plan: Replace AWS Transcribe Diarization with pyannote-audio

## Problem

AWS Transcribe's built-in speaker diarization frequently produces incorrect speaker boundaries — large multi-speaker stretches are assigned to a single label, short back-and-forth turns are collapsed, and the cap on `MaxSpeakerLabels` can silently drop speakers entirely. Our word-level parser in `transcribe_poller.py` is correct; the bad data originates from Transcribe.

## Approach

Split the two responsibilities that AWS Transcribe currently handles alone:

| Responsibility | Current | After |
|---|---|---|
| Speech-to-text + word timestamps | AWS Transcribe | AWS Transcribe (unchanged) |
| Speaker diarization | AWS Transcribe (`ShowSpeakerLabels`) | pyannote-audio 4.x |

AWS Transcribe continues to produce word-level timestamps with high accuracy. pyannote-audio runs over the same audio file independently and produces precise speaker turn boundaries. We then align Transcribe's words to pyannote's turns to get the final segmented transcript.

The ECAPA-TDNN model already in the worker is **not replaced** — it continues to be used for speaker profile matching against stored `SpeakerSample` embeddings in the DB. pyannote uses its own internal embedding model solely for diarization.

## Architecture After

```
Source audio (S3)
    │
    ├─► AWS Transcribe ──────────────────────────────────► word list
    │   (ASR only, ShowSpeakerLabels=False)                [{word, start, end}, ...]
    │
    └─► pyannote-audio pipeline ──────────────────────────► speaker turns (two variants)
        (run in worker against downloaded audio)           regular:    [{speaker, start, end}]  <- overlaps present
                │                                          exclusive:  [{speaker, start, end}]  <- no overlaps
                │
                ├─ align words to exclusive turns ────────► diarized segments
                │                                          [{speaker_label, start, end, text}, ...]
                │
                └─ regular vs exclusive diff ─────────────► overlap segments
                                                           [{start, end, speakers: [...]}, ...]
                                                                    │
                                                                    ▼
                                                     ECAPA-TDNN embed per speaker label
                                                                    │
                                                                    ▼
                                                     cosine match to SpeakerProfile DB
```

**Why both diarization variants:**
- **Exclusive** diarization assigns each timestamp to exactly one speaker — no overlapping segments. Used for word alignment since each word maps unambiguously to one speaker.
- **Regular** diarization preserves overlapping speech events. Diffing the two surfaces segments where multiple speakers talked simultaneously, which can be stored as metadata on the job for display in the UI.

---

## Phase 1: Prerequisites

### 1.1 Accept pyannote model licence on HuggingFace — **DONE**

### 1.2 Store token in AWS Secrets Manager — **DONE**

Secret ARN: `arn:aws:secretsmanager:us-east-1:123456789012:secret:transcription-prod/huggingface-token-iSRtpJ`

**Pending:** The ECS task role must be granted `secretsmanager:GetSecretValue` on this ARN before deployment:

```json
{
  "Effect": "Allow",
  "Action": "secretsmanager:GetSecretValue",
  "Resource": "arn:aws:secretsmanager:us-east-1:123456789012:secret:transcription-prod/huggingface-token-iSRtpJ"
}
```

Add this to the ECS task role in Terraform (`infra/`) as part of the Phase 4 infra changes.

---

## Phase 2: `chat-api` changes

**File:** `chat-api/app/services/audio_storage.py`

Remove `ShowSpeakerLabels` and `MaxSpeakerLabels` from the Transcribe API call. Transcribe no longer needs to do diarization; we only want word timestamps.

```python
# Before
Settings={
    "ShowSpeakerLabels": True,
    "MaxSpeakerLabels": max(2, speaker_count_hint),
},

# After
# (no Settings block needed — Transcribe defaults produce word timestamps)
```

`speaker_count_hint` and `speaker_ids` are still stored on the job and passed to the worker via SQS — the worker uses them to hint pyannote's `min_speakers`/`max_speakers`.

No schema migrations, no API changes.

---

## Phase 3: `transcription-worker` changes

### 3.1 `pyproject.toml`

Update the comment noting large packages installed separately in Dockerfile:

```toml
# pyannote.audio, torch, torchaudio, speechbrain installed separately in Dockerfile (large packages)
```

### 3.2 `config.py`

Add new settings. `PYANNOTE_CACHE` is removed — pyannote 4.x dropped its own cache env var; `HF_HOME` is used instead.

```python
HUGGINGFACE_TOKEN: str = ""
PYANNOTE_MODEL: str = "pyannote/speaker-diarization-community-1"
```

### 3.3 New file: `services/diarizer.py`

Singleton wrapper around the pyannote pipeline. Returns both the regular and exclusive diarization so callers can use whichever is appropriate.

```python
from pyannote.audio import Pipeline
import torch


class PyannoteDiarizer:
    _instance: "PyannoteDiarizer | None" = None

    @classmethod
    def get(cls) -> "PyannoteDiarizer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        from config import Settings
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

        output = self.pipeline(audio_path, **kwargs)

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
            "exclusive_turns": _to_turns(output.exclusive_speaker_diarization),
        }
```

Key differences from the old 3.x plan:
- `token=` replaces the removed `use_auth_token=` parameter
- No `cache_dir=` — pyannote 4.x uses `HF_HOME` (set via `ENV` in Dockerfile)
- `pipeline.to(torch.device("cuda"))` called automatically when GPU is available
- Both diarization variants returned; callers choose which to use

### 3.4 `services/transcribe_poller.py`

Add a new method `parse_words(transcript_json)` that extracts only word-level timestamps without touching speaker labels. The existing `parse_diarized_transcript` can be kept for reference/tests but is no longer called by the main pipeline.

```python
def parse_words(self, transcript_json: dict) -> list[dict]:
    """
    Returns list of {word, start_time, end_time} from AWS Transcribe output.
    Punctuation tokens (no timestamps) are attached to the preceding word.
    """
    items = transcript_json.get("results", {}).get("items", [])
    words = []
    for item in items:
        if item["type"] == "punctuation":
            if words:
                words[-1]["word"] += item["alternatives"][0]["content"]
            continue
        words.append({
            "word": item["alternatives"][0]["content"],
            "start_time": float(item["start_time"]),
            "end_time": float(item["end_time"]),
        })
    return words
```

### 3.5 New helper: `services/aligner.py`

Two functions: one that aligns words to speaker turns (using exclusive turns), and one that detects overlapping segments (by diffing the two turn variants).

```python
def align_words_to_turns(
    words: list[dict],            # [{word, start_time, end_time}]
    exclusive_turns: list[dict],  # [{speaker_label, start, end}] no overlaps, sorted by start
) -> list[dict]:
    """
    Uses exclusive_speaker_diarization turns so each word maps to exactly one speaker.
    For each word, assigns it to the turn containing its midpoint.
    Words in gaps (silence) are assigned to the nearest turn.
    Consecutive words with the same speaker are merged into segments.
    Returns [{speaker_label, start_time, end_time, text}].
    """
    ...


def find_overlaps(
    turns: list[dict],            # [{speaker_label, start, end}] regular diarization
    exclusive_turns: list[dict],  # [{speaker_label, start, end}] exclusive diarization
) -> list[dict]:
    """
    Segments present in `turns` but absent from `exclusive_turns` represent
    overlapping speech. Returns [{start, end, speakers: [...]}].
    """
    ...
```

Alignment logic for `align_words_to_turns`:
1. For each word, compute `midpoint = (start_time + end_time) / 2`.
2. Find the turn where `turn.start <= midpoint < turn.end`.
3. If no turn contains the midpoint (word is in a gap), assign to the turn with the nearest endpoint.
4. Group consecutive same-speaker words into segments.

### 3.6 `handlers/transcription.py`

Replace the current pipeline steps 5–6 with the new approach:

```python
from services.diarizer import PyannoteDiarizer
from services.aligner import align_words_to_turns, find_overlaps

# 5a. Extract word timestamps from Transcribe (no speaker info)
words = poller.parse_words(transcript_json)

# 5b. Run pyannote diarization on the source audio file
diarizer = PyannoteDiarizer.get()
max_spk = max(
    (len(speaker_ids) if speaker_ids else 0),
    job.speaker_count_hint or 0,
) or None
diarization = diarizer.diarize(
    tmp_path,        # path to source audio already downloaded for embedding
    min_speakers=1,
    max_speakers=max_spk,
)

# 5c. Align words to exclusive turns (one speaker per timestamp)
segments = align_words_to_turns(words, diarization["exclusive_turns"])

# 5d. Detect overlapping speech for metadata
overlaps = find_overlaps(diarization["turns"], diarization["exclusive_turns"])
# store overlaps on job or segments as needed
```

The audio file is already downloaded in step 6 for embedding; reuse that path so we don't fetch twice.

Everything from step 6 onward (embedding, matching, DB writes, S3 output) is unchanged.

### 3.7 New file: `services/spot_watcher.py`

Polls the EC2 instance metadata endpoint for a Spot interruption notice. On a 2-minute warning, immediately releases the SQS message back to the queue so another instance can pick it up without waiting out the full visibility timeout.

```python
import threading
import time
import logging
import requests
import boto3

logger = logging.getLogger(__name__)

_METADATA_URL = "http://169.254.169.254/latest/meta-data/spot/termination-time"
_POLL_INTERVAL = 5  # seconds


class SpotWatcher:
    def __init__(self, queue_url: str, receipt_handle: str, region: str):
        self._queue_url = queue_url
        self._receipt_handle = receipt_handle
        self._sqs = boto3.client("sqs", region_name=region)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(_POLL_INTERVAL):
            try:
                r = requests.get(_METADATA_URL, timeout=1)
                if r.status_code == 200:
                    logger.warning("Spot interruption notice received — releasing SQS message")
                    self._sqs.change_message_visibility(
                        QueueUrl=self._queue_url,
                        ReceiptHandle=self._receipt_handle,
                        VisibilityTimeout=0,
                    )
                    return
            except Exception:
                pass  # metadata endpoint unavailable (non-EC2 env, unit tests, etc.)
```

Usage in the main SQS loop:

```python
watcher = SpotWatcher(settings.SQS_QUEUE_URL, receipt_handle, settings.AWS_REGION)
watcher.start()
try:
    process_message(body, settings)
finally:
    watcher.stop()
```

The watcher is a no-op on non-EC2 environments (Fargate, local dev) — the metadata endpoint simply times out.

### 3.8 `Dockerfile`

Install `pyannote.audio==4.0.4` **before** speechbrain so pyannote's pinned torch/torchcodec/torchaudio versions take precedence (pyannote 4.0.2+ pins these to avoid a known segfault). Pre-download the pyannote model at build time via `HF_HOME`.

**CPU build (current baseline):**

```dockerfile
ARG HUGGINGFACE_TOKEN

# pyannote 4.x pins torch/torchcodec/torchaudio — install first so its versions win
RUN pip install --no-cache-dir "pyannote.audio==4.0.4"
RUN pip install --no-cache-dir speechbrain pydub boto3 pydantic-settings pgvector asyncpg sqlalchemy psycopg2-binary scipy requests

# Pre-download pyannote model at build time
ENV HF_HOME=/app/hf_cache
RUN python -c "\
from pyannote.audio import Pipeline; \
Pipeline.from_pretrained( \
    'pyannote/speaker-diarization-community-1', \
    revision='<commit-sha>', \
    token='${HUGGINGFACE_TOKEN}', \
)"
```

**GPU build (Phase 4.0):** Different base image — see that section.

Build command: `docker build --build-arg HUGGINGFACE_TOKEN=hf_xxxx -t transcription-worker .`

In CI (`.github/workflows/deploy.yml`), pass `--build-arg HUGGINGFACE_TOKEN=${{ secrets.HUGGINGFACE_TOKEN }}`.

**Model commit pinning:** Replace `<commit-sha>` with the SHA obtained from:
```bash
python -c "from huggingface_hub import model_info; print(model_info('pyannote/speaker-diarization-community-1').sha)"
```
Run this once after confirming the model works, then hardcode the SHA. Matches the pattern used for the SpeechBrain model (`revision='0f99f2d...'`).

---

## Phase 4: Infrastructure changes

### 4.0 GPU + Spot: Switch from Fargate to EC2 launch type

GPU acceleration isn't available on Fargate. The task therefore needs the **EC2 launch type** with GPU-capable instances. Spot instances are used to reduce cost.

**Recommended instance:** `g4dn.xlarge` — 4 vCPU, 16 GB RAM, 1× NVIDIA T4 (16 GB VRAM), ~$0.16/hr Spot.

pyannote diarization on a T4 GPU runs at roughly 10–30× real-time. A 30-minute file processes in under 2 minutes on GPU.

**Why Spot is safe here:** If an instance is reclaimed mid-job, the `SpotWatcher` (Phase 3.7) catches the 2-minute warning and immediately releases the SQS message back to the queue. Another instance picks it up without delay. Jobs are idempotent — reprocessing a job overwrites its DB rows and S3 output cleanly.

**Infrastructure changes required (Terraform in `infra/`):**

- Create an EC2 Auto Scaling Group using the ECS GPU-optimized AMI (`al2023-ami-ecs-gpu-*`) with a Spot-weighted mixed instances policy targeting `g4dn.xlarge`.
- Register it with the `chat-api-prod` cluster as a Spot capacity provider.
- ECS task definition: add `resourceRequirements: [{ type: "GPU", value: "1" }]`; change `requiresCompatibilities` from `["FARGATE"]` to `["EC2"]`.
- Add `secretsmanager:GetSecretValue` on the HF token ARN to the ECS task role (see Phase 1.2).

**Dockerfile changes for GPU:** Replace the slim Python base image and CPU torch wheels:

```dockerfile
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y python3.11 python3-pip ffmpeg git && \
    rm -rf /var/lib/apt/lists/*
RUN ln -s /usr/bin/python3.11 /usr/bin/python

WORKDIR /app
COPY pyproject.toml .

ARG HUGGINGFACE_TOKEN

# pyannote 4.x pins torch/torchcodec/torchaudio — install first so its versions win
RUN pip install --no-cache-dir "pyannote.audio==4.0.4"
RUN pip install --no-cache-dir speechbrain pydub boto3 pydantic-settings pgvector asyncpg sqlalchemy psycopg2-binary scipy requests

ENV HF_HOME=/app/hf_cache
RUN python -c "\
from pyannote.audio import Pipeline; \
Pipeline.from_pretrained( \
    'pyannote/speaker-diarization-community-1', \
    revision='<commit-sha>', \
    token='${HUGGINGFACE_TOKEN}', \
)"

COPY . .
CMD ["python", "main.py"]
```

The `PyannoteDiarizer` singleton already calls `pipeline.to(torch.device("cuda"))` when a GPU is present — no other code changes needed.

### 4.1 ECS task memory

Both models load into memory simultaneously:

| Component | Memory |
|---|---|
| pyannote diarization pipeline | ~1.5 GB |
| ECAPA-TDNN (SpeechBrain) | ~0.3 GB |
| Worker overhead + audio buffers | ~0.5 GB |
| **Total** | **~2.3 GB** |

`g4dn.xlarge` has 16 GB RAM — no task memory limit concern. Set task `memory` to `6144` to leave headroom for spikes.

### 4.2 SQS visibility timeout

With GPU, pyannote diarization is fast. A 30-minute file processes in ~2 minutes on a T4. `SQS_VISIBILITY_TIMEOUT=600` (10 min) is sufficient and conservative.

The `SpotWatcher` makes the visibility timeout less critical for Spot interruptions — the message is released immediately on a 2-minute warning rather than waiting out the full timeout.

---

## Phase 5: Testing

### 5.1 Unit tests — `tests/test_aligner.py` (new)

Pure Python, no models needed. Test `align_words_to_turns` with:
- Normal case: words fully covered by turns
- Gap case: words between turns assigned to nearest
- Single speaker
- Many speakers with short turns (the problem case)

Test `find_overlaps` with:
- No overlaps: exclusive == regular; returns empty list
- One overlap: single segment appears in regular but not exclusive

### 5.2 Unit tests — `tests/test_transcribe_poller.py` (update)

Add tests for `parse_words` (punctuation attachment, empty input). Existing `parse_diarized_transcript` tests can stay unchanged.

### 5.3 Unit tests — `tests/test_spot_watcher.py` (new)

Mock the metadata endpoint and SQS client. Verify that a 200 response triggers `change_message_visibility(VisibilityTimeout=0)` and a non-200/timeout does not.

### 5.4 Integration smoke test (manual)

Before deploying to prod, run the worker locally against a real short audio file:

```bash
python -c "
from services.diarizer import PyannoteDiarizer
d = PyannoteDiarizer.get()
result = d.diarize('test.wav')
print('Regular turns:', len(result['turns']))
print('Exclusive turns:', len(result['exclusive_turns']))
for t in result['exclusive_turns']:
    print(t)
"
```

---

## Phase 6: Rollout

1. ~~Phase 1: HuggingFace licence + secret~~ — done.
2. Implement Phase 2 (`chat-api` Transcribe settings) and deploy `chat-api`.
3. Implement Phase 3 (`transcription-worker` code changes) and Phase 4 (infra) together — deploy worker.
4. Run manual smoke test on a real recording.
5. Monitor CloudWatch `TranscriptionJobDuration` and `SpeakerMatchSuccessRate` metrics.

Phases 2 and 3 can be deployed independently. Deploy the worker update first or simultaneously with the `chat-api` change to avoid a window where the worker still expects Transcribe's speaker labels.

---

## Files Changed Summary

| File | Change |
|---|---|
| `chat-api/app/services/audio_storage.py` | Remove `ShowSpeakerLabels` / `MaxSpeakerLabels` from Transcribe job settings |
| `transcription-worker/config.py` | Add `HUGGINGFACE_TOKEN`, `PYANNOTE_MODEL`; remove `PYANNOTE_CACHE` |
| `transcription-worker/services/diarizer.py` | **New** — `PyannoteDiarizer` singleton; returns both turn variants |
| `transcription-worker/services/aligner.py` | **New** — `align_words_to_turns()` (uses exclusive), `find_overlaps()` |
| `transcription-worker/services/spot_watcher.py` | **New** — `SpotWatcher` thread; releases SQS message on Spot interruption |
| `transcription-worker/services/transcribe_poller.py` | Add `parse_words()` method |
| `transcription-worker/handlers/transcription.py` | Replace Transcribe diarization with pyannote + aligner; start/stop SpotWatcher |
| `transcription-worker/Dockerfile` | CUDA base image; install `pyannote.audio==4.0.4`; pre-download model via `HF_HOME`; pin model commit |
| `transcription-worker/tests/test_aligner.py` | **New** — unit tests for aligner and overlap detection |
| `transcription-worker/tests/test_transcribe_poller.py` | Add `parse_words` tests |
| `transcription-worker/tests/test_spot_watcher.py` | **New** — unit tests for Spot interruption handler |
| `.github/workflows/deploy.yml` | Pass `HUGGINGFACE_TOKEN` build arg from repository secret |
| `infra/` (Terraform) | EC2 Spot capacity provider; GPU task definition; ECS task role `secretsmanager:GetSecretValue` on HF token ARN |

---

## Open Questions

- **pyannote model commit SHA**: Run `python -c "from huggingface_hub import model_info; print(model_info('pyannote/speaker-diarization-community-1').sha)"` after the first successful integration test and hardcode the result into the Dockerfile `revision=` argument.
- **SpeechBrain torch compatibility**: pyannote 4.0.2+ pins specific torch/torchcodec/torchaudio versions to avoid a segfault. SpeechBrain must be compatible. Verify during the first Docker build; if incompatible, pin speechbrain to a version that supports pyannote's torch.
