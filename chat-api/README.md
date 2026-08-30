# chat-api

FastAPI · AWS Bedrock · Cognito · PostgreSQL (EC2-hosted, pgvector) · ECS Fargate

## Quick start (local)

```bash
cp .env.example .env          # fill in values
pip install uv
uv sync --extra dev
docker run -d --name chatapi-pg-dev -p 5433:5432 -e POSTGRES_PASSWORD=<pw> -e POSTGRES_DB=chatapi pgvector/pgvector:pg16
uv run alembic -c app/db/alembic.ini upgrade head
uv run scripts/run_local.sh   # uvicorn --reload on port 8000
```

The pgvector container on 5433 is the working local database (`docker compose up` still uses
`postgres:16-alpine`, which lacks pgvector — the speaker-embedding migration fails on it; see
`docs/TODO.md`). Point `DATABASE_URL` in `.env` at 5433.

For a fully offline setup set `USE_MOCK_BEDROCK=true`, `USE_MOCK_TRANSCRIPTION=true`,
`USE_MOCK_PHOTOGRAMMETRY=true` and `DEV_AUTH_BYPASS=true` — no AWS credentials or Cognito needed;
see `docs/mock-api.md`. `CORS_ORIGINS` must include `http://localhost:5173` (the Vite dev server),
and open the SPA on `localhost`, not `127.0.0.1`.

## Migrations

```bash
# Create a new migration
uv run alembic -c app/db/alembic.ini revision --autogenerate -m "your message"

# Apply
uv run alembic -c app/db/alembic.ini upgrade head
```

## Tests

```bash
uv run pytest -q                     # whole suite, no external deps (tests/integration/ holds only stubs)
```

## Lint / type-check

```bash
uv run ruff check .
uv run ruff format .
uv run mypy app
```

## Logs

All application logs are emitted as single-line JSON to stdout, captured by ECS and forwarded to CloudWatch Logs.

**Log groups** (30-day retention):

| Environment | Log group |
|---|---|
| dev | `/ecs/chat-api-dev` |
| staging | `/ecs/chat-api-staging` |
| prod | `/ecs/chat-api-prod` |

**Structured fields** included on every log line:

| Field | When present |
|---|---|
| `level` | Always |
| `logger` | Always |
| `message` | Always |
| `user_id` | Authenticated requests |
| `conversation_id` | Chat requests |
| `exception` | Error logs |

**Example CloudWatch Logs Insights query** — all errors in the last hour:

```
fields @timestamp, level, message, user_id, conversation_id, exception
| filter level = "ERROR"
| sort @timestamp desc
| limit 50
```

**Log level** is controlled by the `LOG_LEVEL` env var (default: `INFO`). Set `LOG_LEVEL=DEBUG` for verbose output during local dev.

Gunicorn access and error logs are also written to stdout in the container and appear in the same CloudWatch stream.

## Health checks

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health` | Liveness — returns `{"status": "ok"}` |
| `GET /api/v1/health/ready` | Readiness — runs `SELECT 1` against the database |

The ALB target group polls `GET /api/v1/health` every 30 seconds (healthy after 2 passes, unhealthy after 3 failures). ECS will replace a task if it stays unhealthy.

## Monitoring

**ECS Container Insights** is enabled on all clusters. It provides container-level CPU, memory, network, and task count metrics in CloudWatch under the `ECS/ContainerInsights` namespace — visible in the AWS Console under CloudWatch → Container Insights.

**PostgreSQL** is EC2-hosted (RDS was decommissioned 2026-03-15) — there are no `AWS/RDS` metrics; watch the instance's `AWS/EC2` metrics and disk from the host.

**GPU workers** log to `/ecs/transcription-worker-prod` and `/ecs/photogrammetry-prod-worker`; the GPU pool's state (ASG, tasks, queue depth) is one command: `scripts/deploy/gpu-status.sh`.

**No CloudWatch alarms are configured yet** — `infra/modules/monitoring/` is a placeholder. Candidates for first alarms: 5xx error rate, ECS task restarts, ALB unhealthy host count, and the DLQs' message count.

## Project layout

```
app/
  main.py          FastAPI app factory; registers CORS, exception handlers, v1 router
  config.py        Pydantic Settings loaded from .env; accessed via get_settings()
  dependencies.py  FastAPI DI: get_db (async session) and get_current_user (Cognito JWT)
  api/v1/          Versioned route handlers — thin, delegates to services
  services/        Business logic; ChatService orchestrates repo + BedrockService
  repositories/    Async SQLAlchemy queries only; no business logic
  models/          SQLAlchemy ORM models
  schemas/         Pydantic request/response schemas
  core/            logging.py, security.py (Cognito JWKS), exceptions.py
  db/              Session factory + Alembic migrations
tests/             Unit tests (integration/ is stubs)
scripts/           entrypoint.sh (runs migrations, then gunicorn), run_local.sh
```

## Deploy

Push to `main` → `.github/workflows/deploy.yml` → `api.yml`: tests, ECR push, new task-definition
revision, rolling ECS update. Migrations run in the container's entrypoint before gunicorn binds.
Runbook: `docs/runbooks/deploy.md`. Terraform lives at the repo root under `infra/`.
