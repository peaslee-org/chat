# transcription-worker

Standalone Python worker (ECS, EC2 launch type, on the shared GPU capacity provider). Polls an SQS queue and processes audio transcription and speaker diarization jobs. No HTTP server — and no longer a long-lived service either: it's a run-to-completion task, launched per job by the API and exiting itself when idle (see Lifecycle below).

## Key Commands

```bash
# Install dependencies (dev)
pip install -e ".[dev]"

# Run tests (no AWS creds, DB, or ML model needed)
python3 -m pytest tests/ -q

# Run a specific test file
python3 -m pytest tests/test_transcribe_poller.py -q
python3 -m pytest tests/test_matcher.py -q
python3 -m pytest tests/test_aligner.py -q
python3 -m pytest tests/test_spot_watcher.py -q

# Run locally (requires env vars)
python main.py

# Build Docker image (requires HuggingFace token for pyannote model download)
docker build --build-arg HUGGINGFACE_TOKEN=hf_xxx -t transcription-worker .

# Run container locally
docker run --env-file .env transcription-worker
```

## Tests

Unit tests live in `tests/` and require only `pytest` and `scipy` (no SpeechBrain, torch, pyannote, AWS, or DB):

| File | Covers |
|---|---|
| `tests/test_transcribe_poller.py` | `parse_words`: word timestamp extraction; `parse_diarized_transcript` (legacy) |
| `tests/test_matcher.py` | `match_speaker`: threshold logic, multi-sample averaging, best-candidate selection |
| `tests/test_aligner.py` | `align_words_to_turns`: bisect assignment, gap words, overlap detection via `find_overlaps` |
| `tests/test_spot_watcher.py` | SpotWatcher: metadata poll loop, SQS release on interruption notice, no-op on non-EC2 |

## Environment Variables

| Variable | Default | Required |
|---|---|---|
| `DATABASE_URL` | — | yes |
| `AUDIO_BUCKET_NAME` | — | yes |
| `TRANSCRIBE_SQS_QUEUE_URL` | — | yes |
| `AWS_REGION` | `us-east-1` | no |
| `MATCHING_THRESHOLD` | `0.25` | no |
| `SQS_VISIBILITY_TIMEOUT` | `600` | no |
| `SQS_VISIBILITY_EXTENSION_INTERVAL` | `300` | no |
| `SPEECHBRAIN_CHECKPOINT` | `speechbrain/spkrec-ecapa-voxceleb` | no |
| `SPEECHBRAIN_REVISION` | `3c54e95` | no |
| `SPEECHBRAIN_CACHE` | `/app/speechbrain_model` | no |
| `HUGGINGFACE_TOKEN` | `""` | yes (for pyannote model) |
| `PYANNOTE_MODEL` | `pyannote/speaker-diarization-community-1` | no |
| `DEV_CAPTURE_FIXTURES_S3_PREFIX` | `""` | no — set to e.g. `dev-fixtures` to capture pipeline output to S3 |

`DATABASE_URL` may use either `postgresql+asyncpg://` or `postgresql+psycopg2://` scheme — `db.py` normalises it to psycopg2 automatically.

`HUGGINGFACE_TOKEN` is required to load the pyannote diarization model (gated on HuggingFace Hub). In production it is read from an AWS Secrets Manager secret; the ECS task role has `GetSecretValue` on that ARN (`huggingface_token_secret_arn` in the Terraform transcription module).

## Architecture

```
main.py  (SQS poll loop, visibility extender thread, SpotWatcher)
  ├─ handlers/transcription.py   type="transcription_job"
  │    └─ TranscribePoller → PyannoteDiarizer → align_words_to_turns
  │         → EcapaTdnnEmbedder → match_speaker → DB + S3
  └─ handlers/embedding.py       type="sample_embedding"
       └─ S3Client → EcapaTdnnEmbedder → DB
```

**SQS message shapes:**

```json
// transcription_job
{ "type": "transcription_job", "job_id": "<uuid>", "aws_transcribe_job_name": "<name>", "speaker_ids": ["<uuid>", ...] }

// sample_embedding
{ "type": "sample_embedding", "sample_id": "<uuid>", "s3_key": "<s3-key>" }
```

## File Map

| Path | Role |
|---|---|
| `main.py` | Entry point; SQS poll loop; dispatches to `HANDLERS` dict; visibility extender background thread; SpotWatcher per message |
| `config.py` | `pydantic-settings` `Settings` class; all config via env vars |
| `db.py` | Sync SQLAlchemy engine; `get_session()` context manager with auto-commit/rollback |
| `models.py` | SQLAlchemy models duplicated from `chat-api`: `SpeakerProfile`, `SpeakerSample`, `TranscriptionJob`, `TranscriptSegment` |
| `handlers/transcription.py` | Full transcription pipeline (poll → pyannote → align → embed → match → write DB → write S3 → metrics) |
| `handlers/embedding.py` | Download sample audio, generate embedding, update `SpeakerSample` status and `error_message` on failure |
| `services/diarizer.py` | Singleton `PyannoteDiarizer`; loads `pyannote/speaker-diarization-community-1` on CUDA; returns `turns` and `exclusive_turns` |
| `services/aligner.py` | `align_words_to_turns()`: bisect midpoint assignment with gap-word fallback; `find_overlaps()`: sweep-line overlap detection |
| `services/embedder.py` | Singleton `EcapaTdnnEmbedder`; SpeechBrain ECAPA-TDNN; outputs 192-dim L2-normalised vector |
| `services/matcher.py` | `match_speaker()`: cosine distance against averaged per-profile embeddings; returns profile ID or None |
| `services/s3_client.py` | Thin boto3 S3 wrapper: download, upload bytes/text, delete, list |
| `services/transcribe_poller.py` | Polls AWS Transcribe until COMPLETED/FAILED; `parse_words()` extracts word timestamps; `parse_diarized_transcript()` kept for backward compat |
| `services/spot_watcher.py` | `SpotWatcher`: daemon thread polling EC2 metadata every 5 s; on Spot termination notice releases SQS message immediately (VisibilityTimeout=0) |

## Transcription Pipeline (step by step)

1. SQS message received with `job_id` and `aws_transcribe_job_name` (job already started by `chat-api`)
2. DB: set job status → `matching`
3. Poll AWS Transcribe until COMPLETED (30 s interval) — used **only for word-level timestamps**
4. Download transcript JSON from S3; extract `words` via `parse_words()`
5. Download source audio to a temp file; run `PyannoteDiarizer.diarize()` on CUDA
6. `align_words_to_turns()` maps each word to one speaker using exclusive diarization turns (bisect midpoint; gap words go to nearest turn)
7. For each unique speaker label: slice + concatenate audio, export to WAV, upload to S3, generate ECAPA-TDNN embedding
8. Load `ready` `SpeakerSample` rows (filtered to `speaker_ids` if provided)
9. Cosine-distance match each label embedding to candidate speaker profiles (threshold: 0.25)
10. Write `TranscriptSegment` rows to DB
11. Write `transcript.txt` to S3 (`audio/{user_id}/{job_id}/transcript.txt`)
12. Delete temporary segment WAV files from S3
13. DB: set job status → `complete`; emit CloudWatch metrics (`TranscriptionJobDuration`, `SpeakerMatchSuccessRate`)

On any exception: job status → `failed`, `error_message` populated, SQS message left for retry.

**Lifecycle.** The worker is a run-to-completion task: it exits after `IDLE_EXIT_SECONDS` (900) without work — extended by `gpu_sessions.warm_until` — or after `MAX_LIFETIME_SECONDS` (10800), or on a spot-interruption notice (between messages, never mid-job). It records instance id, heartbeat and end reason in `gpu_sessions` (row created by chat-api's RunTask); the ledger is best-effort. Local: `DEV_WORKER_IDLE_EXIT_SECONDS`.

## Data Models

- `SpeakerProfile` — named speaker owned by a user (Cognito sub)
- `SpeakerSample` — audio sample; `status`: `processing → ready | failed`; `embedding`: `Vector(192)` pgvector column; `error_message`: populated on embedding failure
- `TranscriptionJob` — job record; `status`: `pending → transcribing → matching → complete | failed`
- `TranscriptSegment` — timestamped text segment; FK to `TranscriptionJob`; optional FK to `SpeakerProfile` (null = unmatched)

Models are duplicated from `chat-api` intentionally — this worker is deployed independently and must not import from sibling services.

## Deployment

- **CI/CD:** Push to `main` (any change under `transcription-worker/`) triggers root `.github/workflows/worker.yml` — it only registers a new ECS task-definition revision; there is no service to roll, since the API launches the worker per job with `RunTask`
- **Auth:** GitHub Actions OIDC → IAM role `transcription-prod-worker-github-actions`
- **Registry:** ECR repo `transcription-worker-prod` (account `123456789012`, region `us-east-1`); keeps 2 images
- **Runtime:** ECS, EC2 launch type (GPU=1, bridge networking), cluster `chat-api-prod`, on the shared `gpu-<env>` spot capacity provider (`g4dn.xlarge`, min 0 max 2) — not a standing service. Root volume 80 GB. The worker image is also baked into the GPU AMI (`scripts/deploy/build-gpu-ami.sh`) so a cold start after idle doesn't also pull a multi-GB image; rebuild only when the base image or model layers change.
- **Base image:** `nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04` (Python 3.12); requires `>=3.12`
- **Model pre-download:** Both SpeechBrain (ECAPA-TDNN) and pyannote (`pyannote/speaker-diarization-community-1`) are downloaded into the Docker image at build time via `HUGGINGFACE_TOKEN` build arg — no model download at runtime
- **HuggingFace token:** passed as a GitHub Actions secret (`HF_TOKEN`) → Docker `--build-arg`; in ECS the token is injected via Secrets Manager (`huggingface_token_secret_arn`)

## Notes

- `PyannoteDiarizer` and `EcapaTdnnEmbedder` are both singletons (loaded once per worker process). First call initialises each model from the pre-baked image cache.
- The worker is single-threaded for message processing; the visibility extender and SpotWatcher each run on daemon threads.
- `SpotWatcher` is a no-op in local (non-EC2) dev — the metadata endpoint simply times out and is silently ignored. In production the worker always runs on EC2 (spot), so `SpotWatcher` is always live there.
- AWS Transcribe `ShowSpeakerLabels`/`MaxSpeakerLabels` are **not** set — speaker diarization is handled entirely by pyannote; Transcribe is used only for word timestamps.
- `db.py` instantiates `Settings()` at module import time — ensure env vars are set before importing.
- Transcript URI parsing handles both `s3://bucket/key` and HTTPS S3 URL formats from AWS Transcribe.
