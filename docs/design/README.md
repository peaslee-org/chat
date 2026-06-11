# Audio Transcription & Speaker Diarization

Transcribe audio files with named speaker labels. Upload a recording and a short voice sample per speaker — the service identifies who said what.

## How it works

1. **Enroll speakers** — upload a 10–60 s reference clip per person. Voice embeddings are extracted asynchronously using [ECAPA-TDNN](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb).
2. **Submit a job** — upload an audio file (up to 2 GB). AWS Transcribe diarizes the audio into anonymous speaker labels (`spk_0`, `spk_1` …).
3. **Get results** — a Fargate worker matches anonymous labels to enrolled speakers via pgvector cosine similarity and produces a timestamped transcript.

```
[00:00:00]  Alice:   Good morning everyone, let's get started.
[00:00:05]  Bob:     Thanks Alice, I have the Q3 numbers ready.
[00:00:14]  spk_2:   [unmatched] The figures show a 12% increase.
```

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI (Python) |
| Transcription | AWS Transcribe |
| Speaker ID | SpeechBrain ECAPA-TDNN + pgvector (PostgreSQL) |
| Storage | S3 (direct browser upload via pre-signed URL) |
| Async processing | SQS + ECS Fargate |
| Auth | AWS Cognito (JWT) |

## API

Base path: `/api/v1/transcribe/`

**Speakers**
- `POST /speakers` — create a speaker profile
- `POST /speakers/{id}/samples` — upload a reference audio sample
- `DELETE /speakers/{id}` — remove a speaker and their samples

**Jobs**
- `POST /jobs` — submit an audio file for transcription
- `GET /jobs/{id}` — poll job status (`pending` → `transcribing` → `matching` → `complete`)
- `GET /jobs/{id}/transcript` — retrieve the labelled transcript
- `DELETE /jobs/{id}` — delete a job and its data

Full endpoint reference, data model, and infrastructure spec: [`audio_transcription_spec.md`](audio_transcription_spec.md)

## Job lifecycle

```
pending → transcribing → matching → complete
                                  ↘ failed (partial transcript available if Transcribe succeeded)
```

## Limits

| Parameter | Limit |
|---|---|
| Max audio file size | 2 GB |
| Max audio duration | ~4 hours (AWS Transcribe limit) |
| Speaker sample duration | 10 s – 60 s |
| Concurrent jobs per user | 3 |
| Speaker count hint | 2 – 30 |

## Requirements

- Python 3.11+
- PostgreSQL with `pgvector` extension
- AWS account with Transcribe, S3, SQS, and ECS Fargate access
- Docker (worker image ~2.5 GB due to PyTorch)
