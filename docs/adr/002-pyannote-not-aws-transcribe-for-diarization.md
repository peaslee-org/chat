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
- The system already uses a GPU Fargate task for SpeechBrain ECAPA-TDNN embeddings; adding pyannote on the same GPU adds negligible cost
- AWS Transcribe's diarization is less accurate and does not support the overlap detection needed for the sweep-line algorithm in `aligner.py`

## Consequences

- `transcription-worker` requires GPU Fargate (NVIDIA T4 or equivalent)
- The pyannote model is gated on HuggingFace Hub and requires a read token (stored in Secrets Manager)
- `ShowSpeakerLabels` is **not set** in AWS Transcribe job parameters — Transcribe is only for timestamps
- `services/diarizer.py` is the diarization entry point; `services/aligner.py` merges pyannote turns with Transcribe word timestamps
