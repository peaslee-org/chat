# ADR 002 — pyannote-audio for Diarization, Not AWS Transcribe

**Date:** 2026-03-07
**Status:** Accepted

## Context

The system needs speaker diarization (who spoke when) for audio transcription jobs. Two options were considered:

1. **AWS Transcribe** with `ShowSpeakerLabels` — managed service, no GPU needed, simple integration
2. **pyannote-audio** — open-source, runs on GPU, state-of-the-art accuracy

## Decision

Use **pyannote-audio 4.x** (`pyannote/speaker-diarization-community-1`) running on CUDA for speaker diarization. AWS Transcribe is used **only** for word-level timestamps.

## Reason

- pyannote-audio provides significantly better diarization accuracy, especially with overlapping speech
- The system already uses a GPU ECS task (EC2 launch type; see ADR 004) for SpeechBrain ECAPA-TDNN embeddings; adding pyannote on the same GPU adds negligible cost
- AWS Transcribe's diarization is less accurate and does not support the overlap detection needed for the sweep-line algorithm in `aligner.py`

## Consequences

> **Note (2026-08-25):** the worker runs as an EC2-launch-type ECS task on a shared spot GPU
> capacity provider, not Fargate — Fargate has no GPU support. See ADR 004 for the operating model.

- `transcription-worker` requires a GPU (NVIDIA T4 or equivalent)
- The pyannote model is gated on HuggingFace Hub and requires a read token (stored in Secrets Manager)
- `ShowSpeakerLabels` is **not set** in AWS Transcribe job parameters — Transcribe is only for timestamps
- `services/diarizer.py` is the diarization entry point; `services/aligner.py` merges pyannote turns with Transcribe word timestamps
