# AWS Services — Source of Truth

*Read this first when debugging a permission error or planning a new feature.*

Region: `us-east-1` | Account: `123456789012`

## Services

| Service | Resource Name | Purpose | Cost Tier |
|---|---|---|---|
| **ECS** | cluster `chat-api-prod` | Shared cluster, two launch types | Per-vCPU/GB-hour + per-instance |
| **ECS Service** | `chat-api-prod` (on cluster above) | FastAPI backend, standard on-demand launch type | — |
| **ECS Capacity Provider** | `gpu-<env>` (spot ASG, `g4dn.xlarge`, min 0 max 2, managed scaling) | GPU pool the worker's `RunTask` launches onto (EC2 instances — no hardware acceleration on the on-demand type above) — not a standing service | Per-instance-hour while scaled up |
| **ECR** | `chat-api-prod` | Docker images for chat-api | Per GB stored |
| **ECR** | `transcription-worker-prod` | Docker images for transcription-worker | Per GB stored |
| **RDS PostgreSQL** | `chat-api-prod.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com` | Primary DB (PostgreSQL + pgvector) | db.t3.micro or similar |
| **S3** | (see Terraform outputs) | Audio upload staging; transcript output; speaker embeddings | Per GB stored |
| **CloudFront** | (see Terraform outputs) | CDN for chat-vue SPA | Per request |
| **Cognito User Pool** | (see Terraform outputs) | Auth — PKCE OAuth2, JWT RS256 | Per MAU |
| **SQS** | `transcription-prod` | Main transcription job queue | Per request |
| **SQS DLQ** | `transcription-dlq-prod` | Dead-letter queue (maxReceiveCount=3) | Per request |
| **Bedrock** | `anthropic.claude-3-sonnet-20240229-v1:0` | LLM inference | Per token |
| **AWS Transcribe** | — | Word-level timestamps only (diarization is pyannote) | Per minute |
| **Secrets Manager** | `huggingface_token_secret_arn` (see TF var) | HuggingFace token for pyannote model | Per secret/month |
| **CodePipeline/CodeBuild** | `chat-api-prod` | CI/CD for chat-api (migrating to GitHub Actions) | Per build-minute |

## Database

- Host: `chat-api-prod.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:5432`
- DB name: `chatapi`
- Credentials: `DATABASE_URL` env var in ECS task definition
- Extensions: `pgvector` (for `vector(192)` speaker embeddings)

## Key Notes

- `psql` is not in the chat-api container — use `asyncpg` via Python (see root CLAUDE.md for exec pattern)
- Transcription worker runs the EC2 launch type (see ADR 004 for why), launched by `RunTask` on the shared `gpu-<env>` capacity provider; capacity provider is `infra/modules/gpu-capacity/`, the worker task definition and API wiring are `infra/modules/transcription/`
- SQS DLQ CloudWatch alarm is opt-in via `alarm_email` Terraform variable
