# AWS Services — Source of Truth

*Read this first when debugging a permission error or planning a new feature. Names are real
(they are in the Terraform and the code); ids, ARNs and the account number are placeholders here —
the id-level map lives on the private docs track (`docs/private/`).*

Region: `us-east-1` | Account: `123456789012` | Terraform: `infra/environments/prod` (API,
frontend, auth, GPU pool) and `infra/environments/transcription-prod` (workers, queues, audio bucket).

## Compute

| Service | Resource | Purpose | Cost |
|---|---|---|---|
| **ECS cluster** | `chat-api-prod` | One cluster, two launch types | — |
| **ECS service** (Fargate) | `chat-api-prod` | FastAPI backend behind the ALB, 1 task, rolling deploys from CI; migrations run in the container entrypoint | per vCPU/GB-hour |
| **ECS capacity provider** (EC2) | `gpu-prod` → ASG `gpu-prod-*` | GPU pool the workers' `RunTask` lands on. Min 0, max 2, managed scaling (step 1) + managed termination protection. Mixed instances `g4dn.xlarge` / `g4dn.2xlarge` / `g5.xlarge` / `g6.xlarge`; spot vs on-demand set by `gpu_on_demand_percentage` (currently 100 % on-demand while spot placement scores are poor). Pre-baked AMI (`scripts/deploy/build-gpu-ami.sh`) carries both worker images. | per instance-hour while scaled up |
| **ECS task families** (RunTask, no service) | `transcription-prod-worker`, `photogrammetry-prod-worker` | Run-to-completion GPU workers (ADR 004). CI registers a new revision per push; the API launches the family's latest revision. The photogrammetry task mounts host path `/var/lib/photogrammetry` at `/tmp/pg` so stages can resume after a restart. | — |
| **ALB** | `chat-api-prod` | HTTPS in front of the API; listener rules only forward requests carrying the CloudFront secret header | per hour + LCU |
| **ECR** | `chat-api` (keep 10), `transcription-worker-prod` (keep 2), `photogrammetry-prod-worker` (keep 2) | Images tagged with the git SHA + `latest` | per GB |

## Data

| Service | Resource | Purpose | Cost |
|---|---|---|---|
| **PostgreSQL** (self-hosted EC2, outside this Terraform) | `chatapi` database, PostgreSQL 16 + `pgvector` | Conversations, transcription jobs/segments/speaker embeddings, photogrammetry jobs, `gpu_sessions` ledger. DSN is a Secrets Manager secret injected into the API task; RDS was decommissioned 2026-03-15. | instance already paid for |
| **S3** | `chat-audio-prod-<account>` | `audio/` uploads + transcripts (30-day lifecycle); `photogrammetry/<user>/<job>/{input,thumbs,output}/` (30-day lifecycle); `samples/transcribe/…` and `samples/photogrammetry/{images,thumbs}/` (retained). CORS `GET`+`PUT` from the site origin (the 3D viewer fetches the GLB cross-origin). | per GB |
| **S3** | `chat-peaslee-frontend-prod` | SPA build, origin for CloudFront (OAC, no public access) | per GB |
| **Secrets Manager** | `chat-api/prod/database-url`, `chat-api/prod/langsmith-api-key`, `transcription-prod/huggingface-token` | See [secrets.md](secrets.md) | per secret-month |

## Messaging & async

| Service | Resource | Purpose |
|---|---|---|
| **SQS** | `transcription-prod` (+ `transcription-dlq-prod`) | Transcription jobs. Visibility 600 s, retention 4 d, DLQ after 3 receives (DLQ retention 14 d) |
| **SQS** | `photogrammetry-prod` (+ `photogrammetry-prod-dlq`) | Photogrammetry jobs. Visibility 600 s, retention 4 d, DLQ after **5** receives; the worker fails the job row on its last delivery instead of cycling |
| **CloudWatch alarms** | `*-dlq-depth`, `gpu-prod-running-4h` | DLQ non-empty; a GPU instance running > 4 h. Email via SNS when `alarm_email` / `gpu_alert_email` are set |
| **Budgets** | `gpu-prod` | Monthly cost budget on the `CostCenter=gpu` tag |

## Edge & auth

| Service | Resource | Purpose |
|---|---|---|
| **CloudFront** | distribution for `chat.example.com` | SPA from the frontend bucket (SPA-router function), `/api/*` to the ALB with a secret header |
| **ACM** | certificate for `chat.example.com` | CloudFront + ALB TLS |
| **Cognito** | user pool + app client (PKCE, no secret) | Sign-in; API validates RS256 id-tokens against the pool's JWKS |

## AI / media

| Service | Resource | Purpose |
|---|---|---|
| **Bedrock** | `anthropic.claude-3-sonnet-20240229-v1:0` (default; per-conversation `model_id`) | Chat inference |
| **AWS Transcribe** | — | Word-level timestamps only; diarization is pyannote on the GPU worker (ADR 002) |

## Observability

| Log group | Retention | Writer |
|---|---|---|
| `/ecs/chat-api-prod` | per module | API (uvicorn/gunicorn access + app logs, Alembic at startup) |
| `/ecs/transcription-worker-prod` | 30 d | transcription worker |
| `/ecs/photogrammetry-prod-worker` | 30 d | photogrammetry worker (COLMAP/OpenMVS output included) |

## CI/CD identities

GitHub Actions assumes one IAM role per surface via OIDC (no long-lived keys): API deploy
(`github-actions-prod`), frontend deploy (`github-actions-frontend-prod`), and the two worker
roles (`transcription-prod-worker-github-actions`, `photogrammetry-prod-worker-github-actions`).
See [iam.md](iam.md). All four are driven by one workflow, `.github/workflows/deploy.yml`.

## Key notes

- `psql` is not in the API container — use `aws ecs execute-command` on the `chat-api-prod` task and query with `asyncpg` from Python.
- Worker debugging is SSM to the GPU instance (`scripts/deploy/gpu-status.sh` prints it); the worker task itself has no exec.
- A cold GPU start is measured, not guessed: `/gpu/state` quotes the median of recent launches from the `gpu_sessions` ledger (ADR 006).
