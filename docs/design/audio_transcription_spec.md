# Audio Transcription & Speaker Diarization
> **Status (2026-08-29).** Implemented (v1.1 scope): S3 audio bucket, SQS queue + DLQ, worker, four tables, speaker profiles/samples/matching, sample job. Divergences: diarization is done by **pyannote-audio** on the GPU worker, not by AWS Transcribe (see `pyannote-diarization-plan.md` and ADR 002 — Transcribe supplies word timestamps only); PostgreSQL + pgvector is **EC2-hosted**, not RDS; the worker is a run-to-completion ECS EC2 GPU task, not Fargate; deploys via GitHub Actions. Current reference: `chat-api/CLAUDE.md`, `transcription-worker/CLAUDE.md`, `docs/glossary-transcription-diarization.md`.

## Feature Design Specification

**Version:** 1.1 · **Status:** Draft
**API Root:** `/api/v1/transcribe/`
**S3 Prefix:** `audio/{user_id}/{job_id}/`

---

## Overview

This feature ingests a primary audio file alongside short reference samples per named speaker, and produces a time-stamped transcript with speaker labels. AWS Transcribe handles transcription and diarization (producing anonymous labels: `spk_0`, `spk_1` …). A separate async GPU worker (run-to-completion, launched per job) resolves those labels to enrolled speaker names using voice embedding similarity via pgvector.

---

## Architecture

The feature extends the existing AWS architecture with four additions: a dedicated S3 audio bucket, an SQS queue, a GPU speaker-ID worker (EC2 launch type, shared spot capacity provider), and the pgvector extension on the existing RDS instance. Auth, CDN, CI/CD, and the FastAPI service remain unchanged.

**Flow summary:**

```
Browser → POST /api/v1/transcribe/jobs
        → FastAPI validates request, checks concurrent job limit,
          returns { job_id, upload_url } (202)

Browser → PUT {upload_url} (direct-to-S3 upload, bypasses FastAPI)

Browser → POST /api/v1/transcribe/jobs/{job_id}/confirm
        → FastAPI validates S3 object exists, starts AWS Transcribe job,
          enqueues SQS message → 200

SQS → RunTask launches GPU Worker (if not already running)
     → polls Transcribe (extending SQS visibility timeout every 5 min)
     → downloads diarized JSON
     → extracts per-label audio, generates ECAPA-TDNN embeddings
     → pgvector cosine similarity match → named speakers
     → writes transcript.txt to S3, deletes temp segment WAVs
     → updates job status → complete

Browser → GET /api/v1/transcribe/jobs/{job_id}           (poll)
        → GET /api/v1/transcribe/jobs/{job_id}/transcript (retrieve)

Browser → POST /api/v1/transcribe/speakers/{speaker_id}/samples
        → FastAPI validates request, returns { sample_id, upload_url } (202)

Browser → PUT {upload_url} (direct-to-S3 upload)

Browser → POST /api/v1/transcribe/speakers/{speaker_id}/samples/{sample_id}/confirm
        → FastAPI validates S3 object exists, validates duration ≥ 10 s via pydub,
          enqueues sample embedding job → 202 (sample status: processing)

SQS → RunTask launches GPU Worker (shared queue, different message type)
     → downloads sample audio, runs ECAPA-TDNN, stores embedding vector
     → updates speaker_samples.embedding, sets status: ready
```

---

## New AWS Resources

| Resource | Config |
|---|---|
| **S3 — audio bucket** | Separate from Vue SPA assets. Private, SSE-S3 encryption, versioning enabled. Lifecycle: S3-IA at 30 days, expire at 365 days. Additional lifecycle rule: objects under `segments/` prefix expire after 7 days (safety net for worker crash before cleanup). Pre-signed POST policy for all client uploads: 15-min TTL, `content-type` restricted to `audio/*`, `x-amz-content-length-range` enforced (1 byte – 2 GB). Pre-signed GET URLs for downloads: 60-min TTL. |
| **SQS — jobs queue** | Standard queue, 4-day message retention. Visibility timeout 600 s initial; **worker must call `ChangeMessageVisibility` to extend by 600 s every 5 minutes while processing** (prevents duplicate pickup during long Transcribe jobs). DLQ with `maxReceiveCount = 3`. A CloudWatch alarm fires when DLQ depth > 0, triggering a job status update to `failed` via a Lambda or the worker's next poll after being launched. |
| **ECS — GPU worker (EC2 launch type)** | Task definition on the shared `gpu-<env>` spot capacity provider (GPU=1, bridge networking). Launched per job via `RunTask` — not a standing service. Handles both transcription jobs and sample embedding tasks via message type field. ECAPA-TDNN model pinned to **SpeechBrain `speechbrain/spkrec-ecapa-voxceleb` checkpoint, commit `3c54e95`**, baked into the image at build time. Worker image ~7 GB compressed (CUDA + PyTorch + baked models); the image is also baked into the GPU AMI so a cold start doesn't also pull it. |
| **RDS — pgvector extension** | `CREATE EXTENSION IF NOT EXISTS vector;` on existing PostgreSQL instance. Enables `vector(192)` columns (see ADR 001) and cosine similarity (`<=>`) queries for speaker matching. |

**IAM additions:**

- **FastAPI task role:** `transcribe:StartTranscriptionJob`, `transcribe:GetTranscriptionJob`, `s3:PutObject` (audio prefix, for generating pre-signed upload policies), `s3:GetObject` (audio prefix), `s3:DeleteObject` (audio prefix, for job deletion), `sqs:SendMessage`
- **Worker task role:** `transcribe:GetTranscriptionJob`, `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` (all scoped to audio prefix), `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:ChangeMessageVisibility`

---

## Data Model

Four new tables added to the existing RDS instance.

**`speaker_profiles`** — named speaker owned by a user
`id` · `user_id` (Cognito sub) · `speaker_name` · `created_at`

**`speaker_samples`** — reference audio per speaker
`id` · `speaker_profile_id` · `s3_key` · `duration_seconds` · `status` (`processing` → `ready` / `failed`) · `embedding vector(192)` (NULL until worker completes) · `created_at`
*Embedding extracted asynchronously by the worker (same SQS queue, `type: sample_embedding` message). Samples with `status != ready` are excluded from speaker matching.*
*pgvector `ivfflat` index on `embedding` column. Switch to HNSW if per-user embedding count exceeds ~10k.*

**`transcription_jobs`** — one record per job submission
`id` (job_id) · `user_id` · `audio_s3_key` · `aws_transcribe_job_name` · `status` (`pending` → `transcribing` → `matching` → `complete` / `failed`) · `speaker_count_hint` · `transcribe_output_s3_key` · `result_s3_key` · `error_message` (captures failed step name + exception summary) · `created_at` · `updated_at` · `completed_at`

*`updated_at` is set on every status transition. `error_message` format: `"{step}: {exception summary}"`, e.g. `"matching: connection timeout to RDS"`.*

*If the worker fails during the `matching` step but Transcribe has already completed, the job transitions to `failed` but `transcribe_output_s3_key` is preserved. The `GET /jobs/{job_id}/transcript` endpoint returns the raw diarized segments (with anonymous labels) when `status = failed` and `transcribe_output_s3_key` is set, so the transcript is not lost entirely.*

**`transcript_segments`** — individual diarized segments
`id` · `job_id` · `speaker_profile_id` (nullable — `NULL` if unmatched; `ON DELETE SET NULL` so segments survive profile deletion) · `anonymous_label` (always populated, regardless of match outcome — e.g. `spk_0`) · `start_time` · `end_time` · `text`

*Index: `(job_id, start_time)` — required for ordered retrieval without a full table scan.*

### S3 Object Layout

```
audio-{env}-{account_id}/
  audio/
    {user_id}/
      {job_id}/
        source.{ext}           # uploaded audio
        transcript_raw.json    # Transcribe output
        transcript.txt         # final annotated output
        segments/              # temp per-label WAVs, deleted after matching
                               # (7-day lifecycle rule as safety net)
      {speaker_profile_id}/
        samples/{sample_id}.{ext}
```

---

## API Endpoints

All endpoints are relative to the API root `/api/v1/transcribe/`. All require a Cognito JWT Bearer token. **For every endpoint that accepts a path parameter (`job_id`, `speaker_id`, `sample_id`), the API must validate that the resource belongs to the authenticated user's `sub` claim and return `404` if not found or not owned** — do not return `403`, as that leaks resource existence.

### Speaker Management

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/speakers` | Create a named speaker profile. Returns `{ speaker_id, speaker_name }`. |
| `GET` | `/speakers` | List user's speaker profiles. Paginated: accepts `?cursor` and `?limit` (default 20, max 100). Returns `{ items, next_cursor }`. |
| `DELETE` | `/speakers/{speaker_id}` | Delete profile. Cascades: all `speaker_samples` rows deleted, their S3 objects deleted. `transcript_segments.speaker_profile_id` set to NULL (anonymous label retained). |
| `POST` | `/speakers/{speaker_id}/samples` | Begin sample upload. Validates speaker ownership. Returns `{ sample_id, upload_url }` (202). Client must PUT audio directly to S3, then call `/confirm`. |
| `POST` | `/speakers/{speaker_id}/samples/{sample_id}/confirm` | Signal upload complete. API validates S3 object exists, checks duration ≥ 10 s via pydub (returns `422` with `"duration_too_short"` error code if not), enqueues embedding job. Sample `status` becomes `processing`. |
| `DELETE` | `/speakers/{speaker_id}/samples/{sample_id}` | Remove a reference sample. Deletes DB row and S3 object. |

**Sample duration validation:** minimum 10 seconds is required for reliable ECAPA-TDNN embeddings (insufficient speech frames below this threshold). Maximum 60 seconds — longer samples are rejected with `422 "duration_too_long"`. Validation uses `pydub.AudioSegment` on the downloaded S3 object; unsupported formats return `422 "unsupported_format"`.

### Transcription Jobs

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/jobs` | Begin job submission. Checks concurrent job limit: **max 3 active jobs per user** (`status` in `pending`, `transcribing`, `matching`) — returns `429` if exceeded. Returns `{ job_id, upload_url }` (202). Client must PUT audio directly to S3, then call `/confirm`. Optional body params: `speaker_count_hint` (2–30, default 2), `speaker_ids` (restrict matching to listed profiles), `language` (BCP-47 code, default `"en-US"`). |
| `POST` | `/jobs/{job_id}/confirm` | Signal upload complete. API validates S3 object exists and `content-type` is `audio/*`, starts AWS Transcribe job, enqueues SQS message. Job `status` → `transcribing`. Returns `200`. |
| `GET` | `/jobs` | List user's jobs with status. Paginated: accepts `?cursor` and `?limit` (default 20, max 100). Returns `{ items, next_cursor }`. |
| `GET` | `/jobs/{job_id}` | Poll status. Returns full job record including `status`, `updated_at`, and `error_message`. When `status = failed` and `transcribe_output_s3_key` is set, also returns `"partial_transcript_available": true`. |
| `GET` | `/jobs/{job_id}/transcript` | Retrieve segments ordered by `start_time` + pre-signed S3 URL for `transcript.txt`. Available when `status = complete`. When `status = failed` and `partial_transcript_available`, returns raw diarized segments with anonymous labels and no `transcript.txt` URL. Returns `409` if `status` is `pending`, `transcribing`, or `matching`. |
| `DELETE` | `/jobs/{job_id}` | Delete job record, all `transcript_segments` rows, and all associated S3 objects (`source.*`, `transcript_raw.json`, `transcript.txt`, `segments/*`). |

---

## Speaker Matching

### Cosine Distance Threshold

The speaker matching threshold is **cosine distance ≤ 0.25** (equivalently, cosine similarity ≥ 0.75). A segment's anonymous label is resolved to the enrolled speaker with the lowest cosine distance to the segment embedding, provided that distance is ≤ 0.25. If no enrolled speaker meets the threshold, the anonymous label is retained as-is.

**Threshold rationale:** Derived from the ECAPA-TDNN model's equal-error-rate (EER) operating point on VoxCeleb2. At 0.25, false acceptance rate ≈ 3%, false rejection rate ≈ 8% — biased toward avoiding incorrect name assignment. This value is **not user-configurable** in v1.0. If per-deployment tuning is needed in future, add a `matching_threshold` column to `transcription_jobs`.

Matching uses only `speaker_samples` with `status = ready`. If a user has no ready samples, all speakers remain anonymous.

---

## Transcript Output Format

```
[00:00:00]  Alice:   Good morning everyone, let's get started.
[00:00:05]  Bob:     Thanks Alice, I have the Q3 numbers ready.
[00:00:11]  Alice:   Great, please go ahead.
[00:00:14]  spk_2:   [unmatched] The figures show a 12% increase.
```

Unmatched speakers (cosine distance > 0.25, or no enrolled speakers with `status = ready`) fall back to the raw Transcribe anonymous label. The `[unmatched]` tag is included in `transcript.txt` but **not** stored in `transcript_segments.text` — the segment row retains clean text with `speaker_profile_id = NULL`.

---

## Key Dependencies

**FastAPI service additions:** `boto3` (Transcribe + S3 + SQS), `pgvector`, `pydub` (sample duration/format validation), `ffmpeg` (pydub backend)

**Speaker-ID worker:** `boto3`, `speechbrain` + `torch` / `torchaudio` (ECAPA-TDNN embeddings, pinned checkpoint `speechbrain/spkrec-ecapa-voxceleb@3c54e95`), `pydub`, `pgvector`, `scipy` (cosine distance)

---

## Operational Concerns

### CloudWatch Metrics and Alarms

| Metric | Source | Alarm Threshold |
|---|---|---|
| `TranscriptionJobDuration` | Worker (custom metric) | p95 > 3600 s → alert |
| `SpeakerMatchSuccessRate` | Worker (custom metric) | < 70% over 1 hr → alert |
| `DLQDepth` | SQS built-in (`ApproximateNumberOfMessagesVisible`) | > 0 → alert, trigger job failure sweep |
| `WorkerErrorRate` | CloudWatch Logs metric filter on ERROR | > 5 errors / 5 min → alert |
| GPU task running long | ECS `RunningTaskCount` on the worker task family | sustained > 4 hours → alert (the worker should have self-exited via `MAX_LIFETIME_SECONDS` well before this) |
| GPU monthly spend | AWS Budgets, scoped to resources tagged `CostCenter=gpu` | over threshold → alert |

All worker container logs go to CloudWatch log group `/ecs/transcription-worker` with 90-day retention.

### Failed Job Recovery

- When a message lands on the DLQ (after 3 delivery attempts), a CloudWatch alarm triggers. A scheduled Lambda sweeps `transcription_jobs` where `status IN ('transcribing', 'matching')` and `updated_at < NOW() - INTERVAL '2 hours'`, marking them `failed` with `error_message = "exceeded max retries"` — it no longer depends on a worker being up to run it, since the worker now exits between jobs instead of polling continuously.
- Jobs in `failed` status where `transcribe_output_s3_key` is non-null expose partial results via `GET /jobs/{job_id}/transcript` (see API section).
- **Jobs are not automatically retried.** Users must submit a new job. A future `POST /jobs/{job_id}/retry` endpoint can re-enqueue without re-uploading if `audio_s3_key` still exists in S3.

### Temp Segment Cleanup

Per-label WAV files under `segments/` are deleted by the worker immediately after matching completes. A 7-day S3 lifecycle expiration rule on the `segments/` prefix provides a guaranteed cleanup backstop in the event of a worker crash after writing segments but before deleting them.

### SQS Visibility Timeout Extension

The worker extends the SQS message visibility timeout by calling `ChangeMessageVisibility` (reset to 600 s) every 5 minutes during processing. This prevents a second worker from picking up the same message while a long-running Transcribe job is being polled. If the worker process crashes, the timeout expires and the message becomes visible for retry (up to `maxReceiveCount = 3` before DLQ).

---

## Resolved Decisions

| # | Decision |
|---|---|
| 1 | **Maximum audio file size:** 2 GB application cap, enforced via S3 pre-signed POST policy (`x-amz-content-length-range`). Direct browser-to-S3 upload is required — the FastAPI service does not proxy audio data. |
| 2 | **Multi-language support:** `language` parameter (BCP-47) added to `POST /jobs`. Passed directly to Transcribe `LanguageCode`. Defaults to `"en-US"`. |
| 3 | **Speaker count hint:** Optional `speaker_count_hint` (2–30). Defaults to 2 if omitted (Transcribe's default). Note: Transcribe accuracy degrades with inaccurate hints; surface this caveat in the UI. Range increased to 30 to match Transcribe's actual `MaxSpeakerLabels` maximum. |
| 4 | **pgvector index type:** `ivfflat` for v1.0 (suitable for < 10k embeddings per user). Migrate to HNSW when per-user embedding counts approach that limit. |