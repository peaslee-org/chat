# Secrets

*Names only — never values. Nothing here is checked into Terraform state either: the API and
workers receive secrets as ECS `valueFrom` injections.*

## Secrets Manager

| Secret (Terraform variable) | Contents | Consumed by |
|---|---|---|
| `chat-api/prod/database-url` (`database_url_secret_arn`) | PostgreSQL DSN (`postgresql+asyncpg://…`) | chat-api task (`DATABASE_URL`), photogrammetry worker task, transcription worker task |
| `chat-api/prod/langsmith-api-key` (`langchain_api_key_secret_arn`) | LangSmith key, optional tracing | chat-api task (`LANGCHAIN_API_KEY`) |
| `transcription-prod/huggingface-token` (`huggingface_token_secret_arn`) | HuggingFace read token for the gated pyannote model | transcription worker task (`HUGGINGFACE_TOKEN`) |

Rotate by updating the secret value; tasks pick it up on their next start (`gh workflow run
Deploy -f api=true` rolls the API; workers start fresh per job).

## GitHub Actions repository secrets

| Secret | Used by | Purpose |
|---|---|---|
| `AWS_DEPLOY_ROLE_ARN_API` | `api.yml` | OIDC role for the API deploy |
| `AWS_DEPLOY_ROLE_ARN_VUE` | `vue.yml` | OIDC role for the frontend deploy |
| `AWS_DEPLOY_ROLE_ARN_WORKER` | `worker.yml` | OIDC role for the transcription worker |
| `AWS_DEPLOY_ROLE_ARN_PHOTOGRAMMETRY` | `photogrammetry-worker.yml` | OIDC role for the photogrammetry worker |
| `HUGGINGFACE_TOKEN` | `worker.yml` | `--build-arg` to download the pyannote model at image build; not baked into a layer |
| `VITE_API_BASE_URL`, `VITE_COGNITO_DOMAIN`, `VITE_COGNITO_CLIENT_ID`, `VITE_COGNITO_REDIRECT_URI`, `VITE_COGNITO_SCOPE` | `vue.yml` | Build-time config compiled into the SPA (public values, kept as secrets for convenience) |
| `S3_BUCKET`, `CF_DISTRIBUTION_ID` | `vue.yml` | Frontend bucket + distribution to invalidate |

Repository variable: `ECS_ENABLED=true` gates the API's ECS deploy job.

## Local dev

Copy `.env.example` in each sub-project and fill in values locally; never commit `.env`.
`DEV_AUTH_BYPASS=true` (API) + `VITE_DEV_AUTH_BYPASS=true` (Vue) skip Cognito entirely, and
`USE_MOCK_BEDROCK` / `USE_MOCK_TRANSCRIPTION` / `USE_MOCK_PHOTOGRAMMETRY` remove every AWS
dependency — see `docs/mock-api.md`.
