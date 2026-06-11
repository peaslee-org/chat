# ADR 001 — Speaker Embedding Dimension: 192

**Date:** 2026-03-05
**Status:** Accepted

## Context

The transcription-worker uses SpeechBrain's `spkrec-ecapa-voxceleb` model to generate speaker embeddings stored in PostgreSQL via pgvector. The initial schema used `vector(256)` based on the assumption that ECAPA-TDNN outputs 256-dimensional vectors.

## Decision

Use `vector(192)` for the `speaker_samples.embedding` column.

## Reason

The specific model checkpoint pinned to revision `3c54e95` outputs **192-dimensional** embeddings, not 256. Loading this checkpoint and calling it with 256 dimensions causes a runtime shape mismatch error.

## Consequences

- Migration `d4e5f6a7b8c9` changes the column type from `vector(256)` to `vector(192)`
- `embedder.py` and `models.py` must agree on dimension 192
- The same `Vector(192)` type is used in both `chat-api/app/models/transcription.py` and `transcription-worker/models.py` — **keep these in sync**
- All existing embeddings were invalidated and re-generated after migration
