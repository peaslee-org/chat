## Audio Diarization Feature Design

> **Status (2026-08-29).** Early design notes, superseded by `audio_transcription_spec.md` and the pyannote plan. The two-stage design (enrollment embeddings → diarization + matching) is what shipped, with ECAPA-TDNN 192-dim embeddings in pgvector on an **EC2-hosted** PostgreSQL (not RDS). See `transcription-worker/CLAUDE.md`.

### Two-Stage Pipeline

**Stage 1: Speaker Enrollment (embedding extraction)**
- User uploads short reference samples per speaker → extract voice embeddings
- Store embeddings in the DB alongside a "speaker profile" record

**Stage 2: Transcription + Diarization**
- Upload the long audio file → chunk if needed → transcribe + diarize → match segments to enrolled speakers via embedding similarity → return annotated transcript

---

### Model 
 AWS Transcribe handles transcription + diarization labels (Speaker_0, Speaker_1...), then those anonymous labels must be matched to the enrolled speakers using cosine similarity on embeddings from pyannote or speechbrain.

---

### New AWS Resources Needed

**Storage**
- **S3 bucket** (or prefix) for audio uploads — raw files, reference samples, and output transcripts
- Keep audio separate from the Vue SPA assets bucket

**Compute**
- **ECS GPU task, EC2 launch type (async worker)** — diarization is CPU/time-intensive, should NOT block the FastAPI request cycle
  - Triggered via SQS message, not a synchronous HTTP call
  - pyannote/speaker-diarization-3.1 or speechbrain ECAPA-TDNN

**Async coordination**
- **SQS queue** — FastAPI enqueues a job, worker polls and processes
- **Job status table** in RDS — `status: pending | processing | complete | failed`, stores S3 output path

**AI / ML**
- **AWS Transcribe** — managed service, no infra needed, pay-per-minute
  - Supports `start_transcription_job` via boto3 with `ShowSpeakerLabels: true`

**IAM additions**
- ECS task role needs: `transcribe:StartTranscriptionJob`, `transcribe:GetTranscriptionJob`, `s3:PutObject/GetObject` on audio bucket

---

### Data Model Additions

```
SpeakerProfile
  id, user_id (Cognito sub), name, created_at

SpeakerSample
  id, speaker_profile_id, s3_key, embedding (pgvector or JSON)

TranscriptionJob
  id, user_id, audio_s3_key, status, result_s3_key,
  conversation_id (optional FK), created_at, completed_at

TranscriptSegment
  id, job_id, speaker_profile_id (nullable), start_time,
  end_time, text
```

Consider adding **pgvector** extension to your RDS instance for efficient embedding similarity search.

---

### API Endpoints to Add

```
POST /api/v1/speakers              # create speaker profile
POST /api/v1/speakers/{id}/samples # upload reference audio sample
POST /api/v1/transcriptions        # submit audio file for processing
GET  /api/v1/transcriptions/{id}   # poll job status
GET  /api/v1/transcriptions/{id}/transcript  # fetch result
```

---

### Architecture Flow

```
Browser uploads audio → S3 (presigned URL)
  → POST /api/v1/transcriptions → FastAPI enqueues SQS message → returns job_id

SQS Worker (ECS, EC2 GPU capacity provider):
  1. Download audio from S3
  2. Submit to AWS Transcribe (with speaker diarization)
  3. Poll until complete, download JSON result
  4. For each diarized segment, extract embedding snippet
  5. Compare against enrolled speaker embeddings (cosine sim)
  6. Map Speaker_0/1/2 → named speakers
  7. Write annotated transcript to S3 + TranscriptSegment rows
  8. Update job status → complete

Browser polls GET /transcriptions/{id} → gets download link when done
```

---

### Key Caveats

- **AWS Transcribe diarization** works well for 2-5 speakers but degrades with more; pyannote is more accurate if you need robustness
- **Speaker matching accuracy** depends heavily on reference sample quality — recommend 30–60 seconds of clean speech per speaker
- Audio files can be large — use **presigned S3 URLs** for direct browser-to-S3 uploads rather than proxying through FastAPI
- AWS Transcribe is **asynchronous by nature** (no streaming diarization), so the SQS/polling pattern is the right fit