# chat

An AI-powered chat application with audio transcription, speaker diarization and photo-to-3D scanning. Users chat with Claude via AWS Bedrock, upload recordings to get speaker-identified transcripts, and upload a set of photos to get a textured 3D mesh (COLMAP + OpenMVS on an on-demand GPU worker). User guide: [docs/user-guide.md](docs/user-guide.md).

## Structure

| Directory | Stack | Role |
|---|---|---|
| [chat-api/](chat-api/README.md) | FastAPI, Python, PostgreSQL, AWS Bedrock | Backend REST API |
| [chat-vue/](chat-vue/README.md) | Vue 3, TypeScript, Tailwind CSS, Vite | Frontend SPA (S3 + CloudFront) |
| [transcription-worker/](transcription-worker/CLAUDE.md) | Python, pyannote-audio, SpeechBrain, PyTorch | Run-to-completion GPU worker (ECS, EC2 launch type) — diarization + speaker matching |
| [photogrammetry-worker/](photogrammetry-worker/CLAUDE.md) | Python, COLMAP, OpenMVS, trimesh | Run-to-completion GPU worker — photos → textured GLB |
| [gpu-worker/](gpu-worker/) | Python, boto3, SQLAlchemy | Shared package: run-to-completion loop, session ledger, SQS wiring for both workers |
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
      → SQS → RunTask → transcription-worker (ECS, EC2 launch type, GPU ASG scaled 0→1 on demand)
                  → pyannote-audio diarization (CUDA)
                  → SpeechBrain ECAPA-TDNN speaker matching
                  → PostgreSQL (transcript segments)
                  → S3 (transcript.txt, speaker embeddings)
      → S3 (photo set) → SQS → RunTask → photogrammetry-worker (same GPU pool)
                  → COLMAP → OpenMVS → textured GLB → S3; viewed in-browser with <model-viewer>
```

The GPU pool is an ECS capacity provider over an autoscaling group (min 0, max 2). Workers are
launched per job with `RunTask`, exit when idle, and the group scales back to zero — see ADR 004.

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
- [User guide](docs/user-guide.md) — chat, transcribe, scan
- [ADRs](docs/adr/) — key decisions (vector dimensions, diarization approach, auth flow, run-to-completion GPU task, ordered deploys, API-side thumbnails/estimates)
- [AWS reference](docs/aws/) — services, IAM roles, secrets, networking, quotas
- [Runbooks](docs/runbooks/) — [deploy](docs/runbooks/deploy.md), [SQS drain](docs/runbooks/sqs-drain.md)
- [Design docs](docs/design/) — specs for transcription and photogrammetry; [docs/superpowers/](docs/superpowers/) holds the design/plan documents behind recent batches
- [Backlog](docs/TODO.md) — grouped by deploy surface

## CI/CD

One workflow, [`deploy.yml`](.github/workflows/deploy.yml), runs on every push to `main`: it detects
which directories changed and deploys those surfaces **in dependency order** — `chat-api` first (it
runs the migrations), then `chat-vue` and the workers — by calling the reusable per-surface
workflows. Manual redeploy of one surface: `gh workflow run Deploy -f photogrammetry_worker=true`.

| Reusable workflow | Surface | What it does |
|---|---|---|
| `api.yml` | `chat-api/` | Test → build → push ECR → rolling ECS deploy (migrations at container start) |
| `vue.yml` | `chat-vue/` | Build → S3 sync → CloudFront invalidate |
| `worker.yml` | `transcription-worker/`, `gpu-worker/` | Build → push ECR → register task-definition revision (launched per job, no service) |
| `photogrammetry-worker.yml` | `photogrammetry-worker/`, `gpu-worker/` | Same, for the photogrammetry family |
| `tf-validate.yml` | `infra/` (PRs) | terraform fmt + validate; apply is manual |

Ordering rules and the recovery for a failed run: [docs/runbooks/deploy.md](docs/runbooks/deploy.md).

## Infrastructure

Terraform in [infra/](infra/) — two environments: `prod` (API, frontend, Cognito, GPU pool) and
`transcription-prod` (worker task definitions, queues, audio bucket). Each needs a gitignored
`backend.hcl` and `terraform.tfvars` (copy the `.example` files).

```bash
cd infra/environments/prod
terraform init -backend-config=backend.hcl
terraform plan
terraform apply
```
