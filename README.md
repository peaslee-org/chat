# chat

An AI-powered chat application with audio transcription and speaker diarization. Users can have conversations with Claude via AWS Bedrock and upload audio recordings to get speaker-identified transcripts.

## Structure

| Directory | Stack | Role |
|---|---|---|
| [chat-api/](chat-api/README.md) | FastAPI, Python, PostgreSQL, AWS Bedrock | Backend REST API |
| [chat-vue/](chat-vue/README.md) | Vue 3, TypeScript, Tailwind CSS, Vite | Frontend SPA (S3 + CloudFront) |
| [transcription-worker/](transcription-worker/CLAUDE.md) | Python, pyannote-audio, SpeechBrain, PyTorch | GPU Fargate worker — diarization + speaker matching |
| [infra/](infra/) | Terraform | AWS infrastructure (ECS, EC2 PostgreSQL, S3, CloudFront, Cognito, SQS) |

## Quick start (local dev)

```bash
# 1. Install deps + copy .env files for all sub-projects
./scripts/local/setup.sh

# 2. Fill in the required values
#    chat-api/.env        — DATABASE_URL, COGNITO_*, AWS_*
#    chat-vue/.env.local  — VITE_COGNITO_*, VITE_API_BASE_URL

# 3. Start the API + local Postgres
cd chat-api && docker compose up

# 4. Start the frontend (in a new terminal)
cd chat-vue && npm run dev
# → http://localhost:5173
```

For full offline dev (no AWS credentials needed), set in `chat-api/.env`:

```
USE_MOCK_BEDROCK=true
USE_MOCK_TRANSCRIPTION=true
```

## Architecture

```
Browser (chat-vue SPA — S3 + CloudFront)
  → AWS Cognito (PKCE OAuth2)
  → chat-api (ECS Fargate, FastAPI)
      → PostgreSQL (conversations + transcription jobs)
      → AWS Bedrock (Claude — LLM inference)
      → S3 (audio upload staging)
      → AWS Transcribe (word-level timestamps)
      → SQS → transcription-worker (ECS Fargate GPU)
                  → pyannote-audio diarization (CUDA)
                  → SpeechBrain ECAPA-TDNN speaker matching
                  → PostgreSQL (transcript segments)
                  → S3 (transcript.txt, speaker embeddings)
```

## Scripts

```
scripts/
├── local/
│   ├── setup.sh          — first-time setup: install deps, copy .env files
│   ├── seed-db.sh         — seed local DB with test conversations and speakers
│   └── gpu-dev.sh         — start/stop/ssh to the EC2 GPU dev box
└── deploy/
    ├── migrate.sh         — run Alembic migrations via ECS exec (prod)
    ├── build-api.sh       — build + push chat-api image to ECR
    ├── build-worker.sh    — build + push transcription-worker image to ECR
    ├── build-gpu-ami.sh   — bake the worker image into the ECS GPU AMI (pre-bake, cold-start-free)
    └── gpu-status.sh      — one-screen GPU pool status: ASG, worker tasks, queue depth
```

## Docs

- [Architecture diagrams](docs/architecture/)
- [ADRs](docs/adr/) — key decisions (vector dimensions, diarization approach, auth flow)
- [AWS reference](docs/aws/) — services, IAM roles, secrets, networking
- [Runbooks](docs/runbooks/) — deploy, SQS drain
- [Design docs](docs/design/)

## CI/CD

GitHub Actions workflows in [.github/workflows/](.github/workflows/):

| Workflow | Trigger | What it does |
|---|---|---|
| `api.yml` | Push to `main` (chat-api changes) | Test → build → push ECR → deploy ECS |
| `worker.yml` | Push to `main` (transcription-worker changes) | Test → build → push ECR → deploy ECS |
| `vue.yml` | Push to `main` (chat-vue changes) | Type-check → build → S3 sync → CF invalidate |
| `tf-validate.yml` | PR (infra changes) | terraform fmt + validate |

## Infrastructure

Terraform in [infra/](infra/) — four environments: `dev`, `staging`, `prod`, `transcription-prod`.

```bash
cd infra/environments/prod
terraform init
terraform plan
terraform apply
```
