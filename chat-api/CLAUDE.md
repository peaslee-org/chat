# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Local dev (without Docker):**
```bash
uv sync
uv run scripts/run_local.sh      # uvicorn --reload on port 8000
```

**Local dev (with Docker):**
```bash
cp .env.example .env              # fill in values first
docker compose up                 # api + postgres, port 8000
```

**Tests:**
```bash
uv run pytest tests/unit -q                                               # all unit tests; no external deps needed
uv run pytest tests/unit/services/test_transcription_service.py -q       # transcription service + regression tests
uv run pytest tests/unit/api/test_transcribe_jobs.py -q                  # job endpoint HTTP layer
uv run pytest tests/unit/api/test_transcribe_speakers.py -q              # speaker endpoint HTTP layer
uv run pytest tests/unit/services/test_photogrammetry_service.py -q          # photogrammetry service + mock walk
uv run pytest tests/unit/api/test_photogrammetry_jobs.py -q                  # photogrammetry endpoint HTTP layer
```

Key test classes in `tests/unit/services/test_transcription_service.py`:

| Class | Covers |
|---|---|
| `TestInitiateJobUpload` | Concurrent job limit, S3 key shape |
| `TestConfirmJobUpload` | 404/409/422 guards, Transcribe job start, SQS publish |
| `TestGetJobStatus` | `matched_speaker_count` / `total_segment_count` forwarded from DB (regression) |
| `TestGetTranscript` | Status guards, `speaker_name` from matched profile (regression), partial transcript |
| `TestGetTranscriptSpeakerName` | Speaker name populated / null when unmatched (regression) |
| `TestDeleteJob` | S3 key cleanup, repo delete call |

Note: `tests/integration/` exists but contains only stubs — no integration tests are written yet.

**Lint / type-check:**
```bash
uv run ruff check .
uv run ruff format .
uv run mypy app
```

**Migrations:**
```bash
uv run alembic -c app/db/alembic.ini revision --autogenerate -m "your message"
uv run alembic -c app/db/alembic.ini upgrade head
```

## Architecture

The app follows a layered pattern: **router → endpoint → service → repository/external service**.

```
app/
  main.py          FastAPI app factory; registers CORS, exception handlers, v1 router
  config.py        Pydantic Settings loaded from .env; accessed via get_settings() (lru_cache)
  dependencies.py  FastAPI DI: get_db (async session) and get_current_user (Cognito JWT)
  api/v1/          Versioned HTTP layer — thin, delegates to services
    endpoints/     chat.py, conversations.py, health.py, models.py
    transcribe/    jobs.py, speakers.py, dev.py (mock upload sink), deps.py
    photogrammetry/ jobs.py, deps.py
  services/        Business logic
    chat.py        ChatService: orchestrates conversation repo + BedrockService
    conversation.py ConversationService: list/delete/get_messages
    bedrock.py     BedrockService: Bedrock invocation + model listing
    transcription_service.py  TranscriptionService (real) + LocalTranscriptionService (mock)
    photogrammetry_service.py  PhotogrammetryService (real) + LocalPhotogrammetryService (mock)
    audio_storage.py          S3 presigned URLs, object existence check, Transcribe job start
    sqs_publisher.py          SQS publish for transcription jobs and speaker sample embeddings
  repositories/    Async SQLAlchemy queries only; no business logic
    conversation.py
    transcription.py
    photogrammetry.py
  models/          SQLAlchemy ORM models (inherit from app/models/base.py)
    conversation.py
    transcription.py  SpeakerProfile, SpeakerSample (pgvector embedding), TranscriptionJob, TranscriptSegment
    photogrammetry.py  PhotogrammetryJob
  schemas/         Pydantic request/response schemas
    chat.py, conversation.py, models.py, transcription.py
    photogrammetry.py
  core/            security.py (Cognito JWKS verification), exceptions.py
  db/              session.py (engine + sessionmaker init'd at startup), Alembic migrations
  assets/photogrammetry/  sample photo set + placeholder mesh for the mock
```

**Request flow for chat:**
1. `POST /api/v1/chat` → `dependencies.get_current_user` verifies Cognito JWT (JWKS cached in-process)
2. `ChatService.handle()` — loads or creates a conversation, fetches message history, appends the user message; when creating, stores the `model_id` from the request (falls back to `BEDROCK_MODEL_ID`)
3. `BedrockService.invoke()` — calls `bedrock-runtime` synchronously via boto3 using `conversation.model_id` (falls back to `BEDROCK_MODEL_ID` for legacy rows)
4. Both user and assistant messages are persisted via `ConversationRepository`

**Request flow for transcription:**
1. `POST /api/v1/transcribe/jobs` — creates a `TranscriptionJob` (status: `pending`) and returns a presigned S3 upload URL
2. Client uploads audio directly to S3, then calls `POST /api/v1/transcribe/jobs/{id}/confirm`
3. `TranscriptionService.confirm_job_upload()` — verifies the S3 object exists, starts an AWS Transcribe job (word timestamps only — `ShowSpeakerLabels` is **not** set), publishes an SQS message with the job ID + AWS job name + optional speaker IDs, transitions status to `transcribing`
4. The `transcription-worker` consumes SQS, runs pyannote-audio diarization + ECAPA-TDNN speaker matching, writes segments, and updates job status to `complete` or `failed`
5. Client polls `GET /api/v1/transcribe/jobs/{id}` for status, then fetches `GET /api/v1/transcribe/jobs/{id}/transcript` when ready

**Speaker profile flow:**
- `POST /api/v1/transcribe/speakers` — creates a named speaker profile
- `POST /api/v1/transcribe/speakers/{id}/samples` — returns a presigned S3 upload URL for a voice sample
- `POST /api/v1/transcribe/speakers/{id}/samples/{sid}/confirm` — validates audio (10–60 s, decodeable), transitions to `processing`, publishes SQS message to enqueue embedding generation; a worker updates status to `ready`
- Speaker IDs can be passed at job-confirm time so the worker knows which profiles to match against

**Database:** Async SQLAlchemy with asyncpg driver. `init_db()` is called at lifespan startup; `get_db()` yields an `AsyncSession` that commits on success and rolls back on exception. `SpeakerSample.embedding` uses `pgvector` (`Vector(192)`); `SpeakerSample.error_message` stores embedding failure reason set by the transcription worker.

**Auth:** All endpoints (except `/api/v1/health`) use `get_current_user`, which validates RS256 JWTs against Cognito's JWKS URL. The JWKS response is cached as a module-level global.

**Models endpoint:** `GET /api/v1/models` returns available Bedrock models via `BedrockService.list_models()`.

## CI/CD

`buildspec.yml` defines the AWS CodeBuild pipeline:
1. `uv run pytest tests/unit` must pass
2. Docker image is built and pushed to ECR, tagged with the short commit hash and `latest`
3. `imagedefinitions.json` artifact is used by CodePipeline to update the ECS Fargate service

Infrastructure is Terraform under `infra/` (per-environment in `infra/environments/`, shared modules in `infra/modules/`).

## Environment variables

All settings are in `app/config.py` (`Settings` class). Copy `.env.example` to `.env` for local dev. Key vars:

| Variable | Description |
|---|---|
| `DATABASE_URL` | asyncpg connection string |
| `COGNITO_USER_POOL_ID` | Cognito pool for JWT validation |
| `COGNITO_CLIENT_ID` | Cognito app client ID |
| `AWS_REGION` | AWS region for Bedrock/SQS/S3 |
| `BEDROCK_MODEL_ID` | Default Bedrock model (e.g. `anthropic.claude-3-sonnet-20240229-v1:0`) |
| `USE_MOCK_BEDROCK` | Skip Bedrock, return canned response (local dev without AWS creds) |
| `MOCK_BEDROCK_DELAY_SECONDS` | Artificial delay for mock Bedrock responses |
| `AUDIO_BUCKET_NAME` | S3 bucket for audio uploads and transcription output |
| `TRANSCRIBE_SQS_QUEUE_URL` | SQS queue URL consumed by the transcription worker |
| `MAX_CONCURRENT_JOBS` | Per-user limit on active transcription jobs (default: 3) |
| `USE_MOCK_TRANSCRIPTION` | Skip all AWS Transcribe/SQS calls; simulate job completion in-process |
| `MOCK_UPLOAD_BASE_URL` | Base URL for mock presigned URLs (default: `http://localhost:8000`) |
| `MOCK_SAMPLE_PROCESSING_DELAY_SECONDS` | Delay before mock sample transitions `processing` → `ready` (default: 3) |
| `MOCK_JOB_TRANSCRIBING_DELAY_SECONDS` | Delay in mock job `transcribing` stage (default: 5) |
| `MOCK_JOB_MATCHING_DELAY_SECONDS` | Delay in mock job `matching` stage (default: 3) |
| `USE_MOCK_PHOTOGRAMMETRY` | Skip S3/ECS; jobs walk `queued` → `sfm` → `dense` → `mesh` → `texture` → `complete` on timers and the viewer gets the committed placeholder mesh (`app/assets/photogrammetry/`) |
| `MOCK_PHOTOGRAMMETRY_STAGE_DELAY_SECONDS` | Seconds spent in each mock stage: `queued` → `sfm` → `dense` → `mesh` → `texture` → `complete` (default: 2.0) |
| `PHOTOGRAMMETRY_MAX_IMAGES` | Per-scan max image count (default: 150) |
| `PHOTOGRAMMETRY_SAMPLE_PREFIX` | Shared sample photo set in the audio bucket, uploaded once by hand (`images/0001.jpg` …) |
| `GPU_PHOTOGRAMMETRY_TASK_FAMILY` | ECS task family of the photogrammetry worker; leave empty until it is deployed (`confirm` → 503) |

**GPU controller:** The transcription worker runs as a run-to-completion ECS task launched on-demand by the API via `app/services/gpu_controller.py` (using ECS `RunTask`). It launches when a transcription job is confirmed, when `/api/v1/gpu/warm` is called, or when a status poll detects an active job with an off worker. The controller enforces daily and monthly GPU-hour caps (from environment) and a per-user warm cap tracked in the `gpu_sessions` table. The GPU-related environment variables (`GPU_CONTROLLER_ENABLED`, `GPU_CLUSTER`, `GPU_WORKER_TASK_FAMILY`, `GPU_CAPACITY_PROVIDER`, the cap/rate settings, and `GPU_COST_TAG_KEY`/`GPU_COST_TAG_VALUE` — the cost-allocation tag Cost Explorer is queried by for the usage panel's actual month-to-date figure) are defined in `.env.example`. The `/api/v1/gpu/*` endpoints return 503 Service Unavailable unless `GPU_CONTROLLER_ENABLED=true` or `USE_MOCK_TRANSCRIPTION=true`. The photogrammetry router builds its own GpuController bound to GPU_PHOTOGRAMMETRY_TASK_FAMILY (same cluster, capacity provider and gpu_sessions ledger); while that setting is empty, confirm returns 503 "photogrammetry worker not deployed". **Admin release:** `POST /api/v1/gpu/release?family=…&mode=graceful|immediate` (Cognito `admin` group only; 403 otherwise, 409 with no live worker) writes `release_mode` / `release_requested_at` / `release_requested_by` on the family's open `gpu_sessions` row and clears `warm_until`; the worker's `ReleaseWatcher` (shared `gpu-worker` package) polls the row every 10 s and exits after its current job (`graceful`) or kills it so the message is redelivered to the next worker (`immediate`; photogrammetry runner only — the transcription job path does not poll the flag yet). Ledger `end_reason = released`. Purpose: reload a bad deploy or free a stuck worker without waiting for idle-exit.

**LangSmith tracing (optional):** set `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`, and `LANGCHAIN_PROJECT` to trace Bedrock invocations via the `@traceable` decorator on `BedrockService.invoke()`.

Note: `.env.example` sets `CORS_ORIGINS=["http://localhost:3000"]` — change to `["http://localhost:5173"]` to match the Vite dev server.

In production (`ENVIRONMENT=prod`), `/docs` (Swagger UI) is disabled.

## Mock / local dev notes

- **`USE_MOCK_BEDROCK=true`** — skips AWS Bedrock entirely, returns a canned response.
- **`USE_MOCK_TRANSCRIPTION=true`** — uses `LocalTranscriptionService` instead of the real one. Jobs are completed in-process via `asyncio.create_task`: `transcribing` → `matching` → `complete` with configurable delays. Seeded with 4 mock transcript segments. Samples transition to `ready` after `MOCK_SAMPLE_PROCESSING_DELAY_SECONDS`. Also enables the mock GPU launcher for the `/api/v1/gpu/*` endpoints, so the Warm button and GPU state queries work locally without AWS resources.
- **`/api/v1/transcribe/dev-upload/{path}`** — PUT/GET sink registered at app startup when mock transcription is enabled; acts as a no-op S3 replacement so browser presigned-URL uploads succeed.
- **`USE_MOCK_PHOTOGRAMMETRY=true`** — uses `LocalPhotogrammetryService`. Confirmed jobs walk `queued → processing (sfm → dense → mesh → texture) → complete` with `MOCK_PHOTOGRAMMETRY_STAGE_DELAY_SECONDS` per step, then the placeholder `app/assets/photogrammetry/{mesh.glb,preview.png}` is copied into the dev-upload sink under the job's `output/` keys; every status response carries `mock: true`. `POST /jobs/sample` copies the committed sample photos into the sink and confirms. The `dev-upload` sink is registered when either mock flag is set and its GET serves stored files (the viewer loads the GLB from it).
