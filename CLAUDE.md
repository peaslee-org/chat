# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workspace Structure

This repo contains two independent projects:

| Directory | Stack | Role |
|---|---|---|
| `chat-api/` | FastAPI, Python, PostgreSQL, AWS Bedrock | Backend API |
| `chat-vue/` | Vue 3, TypeScript, Tailwind CSS, Vite | Frontend SPA |
| `transcription-worker/` | Python, pyannote-audio, SpeechBrain, PyTorch, SQS, S3 | Run-to-completion GPU worker (ECS, EC2 launch type) for audio transcription & speaker diarization |
| `gpu-worker/` | Python, boto3, SQLAlchemy, SQS | Shared package (`gpu_worker`) for the run-to-completion loop, session ledger, and SQS wiring used by both worker images |
| `photogrammetry-worker/` | Python, COLMAP, OpenMVS, trimesh, Pillow, SQS, S3 | Run-to-completion GPU worker (ECS, EC2 launch type) for photo → mesh reconstruction (COLMAP → OpenMVS → texturing) |

Each sub-project has its own `CLAUDE.md` with detailed commands, architecture, and env var references. Read the relevant one before working in that project.

## System Architecture

**Runtime flow:**

```
Browser (chat-vue SPA on S3 + CloudFront)
  → AWS Cognito (Hosted UI, PKCE OAuth2 / token exchange)
  → chat-api (ECS Fargate, FastAPI)
      → PostgreSQL (conversation + message storage)
      → AWS Bedrock (LLM inference: Claude via anthropic.claude-3-sonnet-20240229-v1:0)
      → S3 (audio upload staging)
      → AWS Transcribe (word-level timestamps only)
      → SQS → RunTask launches transcription-worker (ECS, EC2 launch type, shared `gpu-<env>` spot
                  capacity provider; pyannote-audio 4.x + SpeechBrain ECAPA-TDNN)
                  → pyannote diarization (CUDA) + word aligner
                  → PostgreSQL (TranscriptSegment / SpeakerProfile writes)
                  → S3 (transcript.txt output, speaker embeddings)
                  → worker exits (idle timeout, max lifetime, or spot notice); ASG scales back to 0
      → S3 (photo sets under photogrammetry/<user>/<job>/input/) → RunTask photogrammetry worker
                  (not yet built — confirm returns 503 until GPU_PHOTOGRAMMETRY_TASK_FAMILY is set;
                  local dev uses the in-process mock, see docs/mock-api.md)
```

**Auth:**
- Frontend uses PKCE (no client secret) to obtain Cognito `id_token`
- All API requests send `Authorization: Bearer <id_token>`
- Backend validates RS256 JWTs against Cognito's JWKS URL; JWKS cached in-process

**Chat data model:**
- A `Conversation` belongs to a Cognito user (by sub claim) and has a `title` auto-set by `ChatService` to the first user message (truncated to 60 chars); the frontend falls back to first message content when `title` is null
- A `Conversation` also stores a `model_id` (the Bedrock model selected when the conversation was created); all subsequent messages in that conversation use the same model
- A `Message` belongs to a `Conversation` and has a `role` (user/assistant)
- Switching conversations loads history via `GET /api/v1/conversations/{id}/messages`; messages are merged into the store and cached in-memory for the session

## Cross-cutting Concerns

- **CORS:** `CORS_ORIGINS` in chat-api must include the CloudFront domain in production and `http://localhost:5173` for local dev
- **Cognito App Client:** must allowlist both the production callback URL and `http://localhost:5173/callback` for local dev
- **Infrastructure:** Terraform under `infra/` manages ECR, ECS, EC2-hosted PostgreSQL, S3, CloudFront, Cognito, and SQS — all resources use the AWS default VPC (tagged `peaslee-org`). RDS was decommissioned 2026-03-15; the database DSN is a Secrets Manager secret injected by ECS (`database_url_secret_arn`); no credential passes through Terraform or its state. Each environment needs two gitignored files beside its `.tf`: `backend.hcl` (state bucket) and `terraform.tfvars` (account-specific names/ARNs) — copy the `.example` files.
- **CI/CD:** GitHub Actions workflows in `.github/workflows/` — `api.yml` (chat-api), `worker.yml` (transcription-worker), `vue.yml` (chat-vue), `tf-validate.yml` (Terraform PRs).
- **Observability:** LangSmith tracing is optional; set `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` in `chat-api` to trace Bedrock calls via the `@traceable` decorator on `BedrockService.invoke()`
- **Transcription worker CI/CD:** Push to `main` (changes under `transcription-worker/`) triggers `.github/workflows/worker.yml`; GitHub Actions OIDC → IAM role `transcription-prod-worker-github-actions`; the workflow only registers a new ECS task-definition revision — there's no service to roll, since the API launches the worker per job with `RunTask`. The image is also baked into the ECS GPU AMI (`scripts/deploy/build-gpu-ami.sh`); rebuild the AMI only when the base image or model layers change.
