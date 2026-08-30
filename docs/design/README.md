# Design documents

Index of the design material in this directory and in `docs/superpowers/`. Newest first.

## Photogrammetry (Scan)

| Doc | What |
|---|---|
| [photogrammetry-worker-spec.md](photogrammetry-worker-spec.md) | The GPU worker: COLMAP → OpenMVS → textured GLB, run-to-completion on the shared pool |
| [photogrammetry-ui-spec.md](photogrammetry-ui-spec.md) | The Scan page: upload, job cards, stage strip, 3D viewer |
| [../superpowers/specs/2026-08-28-photogrammetry-robustness-design.md](../superpowers/specs/2026-08-28-photogrammetry-robustness-design.md) | Resumable stages, no-cycling rule, mesh budget, photo warnings — deployed 2026-08-29 |
| `../superpowers/plans/2026-08-2{6,7,8}-photogrammetry-*.md` | Step-by-step implementation plans behind the three batches (executed; kept for the record) |

## Transcription

| Doc | What |
|---|---|
| [audio_transcription_spec.md](audio_transcription_spec.md) | Feature spec: enrolment, jobs, data model, infrastructure |
| [pyannote-diarization-plan.md](pyannote-diarization-plan.md) | Why pyannote on a GPU worker rather than Transcribe's diarization (ADR 002) |
| [re-diarization-option-b-plan.md](re-diarization-option-b-plan.md) | Re-running diarization on an existing job |
| [transcribe.md](transcribe.md) | Early notes on the Transcribe integration (partly superseded by the spec) |

## Application

| Doc | What |
|---|---|
| [chat-api-spec.md](chat-api-spec.md) / [chat-api-summary.md](chat-api-summary.md) | Backend API spec and summary |
| [chat-vue-spec.md](chat-vue-spec.md) / [chat-vue-summary.md](chat-vue-summary.md) | Frontend spec and summary |
| [workspace-structure-recommendations.md](workspace-structure-recommendations.md) | Monorepo layout review (done) and open questions |
| [chatgpt-ml-build-suggestions.md](chatgpt-ml-build-suggestions.md) | Third-party notes on ML dev/deploy loops, kept for reference |

Decisions live in [`../adr/`](../adr/); operational reference in [`../aws/`](../aws/) and
[`../runbooks/`](../runbooks/); the user-facing guide is [`../user-guide.md`](../user-guide.md).

---

# Audio Transcription & Speaker Diarization (feature overview)

Transcribe audio files with named speaker labels. Upload a recording and a short voice sample per speaker — the service identifies who said what.

## How it works

1. **Enroll speakers** — upload a 10–60 s reference clip per person. Voice embeddings are extracted asynchronously using [ECAPA-TDNN](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb).
2. **Submit a job** — upload an audio file (up to 2 GB). AWS Transcribe diarizes the audio into anonymous speaker labels (`spk_0`, `spk_1` …).
3. **Get results** — a GPU worker (ECS, EC2 launch type, launched per job on the `gpu-<env>` capacity provider) matches anonymous labels to enrolled speakers via pgvector cosine similarity and produces a timestamped transcript.

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
| Async processing | SQS + ECS (EC2 launch type, GPU capacity provider) |
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
- AWS account with Transcribe, S3, SQS, and ECS (EC2 GPU capacity provider) access
- Docker (worker image ~7 GB compressed — CUDA + PyTorch + baked models)
