### `chat-api`

Implements the backend for audio transcription and speaker diarization.

#### Database

Adds four PostgreSQL tables with a `pgvector vector(256)` column for speaker embeddings:

| Table | Purpose |
|---|---|
| `speaker_profiles` | Named speaker identities per user |
| `speaker_samples` | Reference audio samples linked to profiles |
| `transcription_jobs` | Job lifecycle and metadata |
| `transcript_segments` | Per-segment output with resolved speaker labels |

#### Application Layer

Extends `chat-api/` with:

- **SQLAlchemy models** and an **Alembic migration** for the four new tables
- **Pydantic schemas** for request/response validation
- **Repository** for data access abstraction
- **`AudioStorageService`** — generates S3 pre-signed URLs for audio uploads
- **`TranscriptionService`** — business logic orchestrating jobs and speaker resolution

#### API Endpoints

Adds a router sub-package under `/api/v1/transcribe/` with **11 endpoints** covering speaker profile management and transcription job lifecycle.

#### Transcription Worker

Introduces `transcription-worker/` — a separate Fargate Docker image (~2.5 GB) that:

- Polls an **SQS queue** for new jobs
- Runs **AWS Transcribe** for speech-to-text
- Generates **ECAPA-TDNN speaker embeddings** via SpeechBrain (checkpoint `3c54e95`)
- Resolves speaker labels via **pgvector cosine similarity** (threshold ≤ 0.25)
- Writes the final annotated transcript to **S3**

---

**Spec:** `docs/transcribe/chat-api-spec.md`
