# chat-api

FastAPI · AWS Bedrock · Cognito · PostgreSQL · ECS Fargate

## Quick start (local)

```bash
cp .env.example .env          # fill in values
docker compose up             # starts api + postgres on port 8000
```

Or without Docker:

```bash
pip install uv
uv sync
uv run scripts/run_local.sh   # uvicorn --reload on port 8000
```

Set `USE_MOCK_BEDROCK=true` in `.env` to skip AWS Bedrock and return a canned response — useful without AWS credentials.

Note: `.env.example` sets `CORS_ORIGINS=["http://localhost:3000"]` — change to `["http://localhost:5173"]` to match the Vite dev server.

## Migrations

```bash
# Create a new migration
uv run alembic -c app/db/alembic.ini revision --autogenerate -m "your message"

# Apply
uv run alembic -c app/db/alembic.ini upgrade head
```

## Tests

```bash
uv run pytest tests/unit -q          # no external deps needed
uv run pytest tests/ -q              # requires a running test database (chatapi_test)
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

**RDS** metrics (CPU, connections, free storage, IOPS) are available in CloudWatch under the `AWS/RDS` namespace. Automated backups are retained for 7 days. Deletion protection is enabled for prod.

**No CloudWatch alarms are configured yet** — `infra/modules/monitoring/` is a placeholder. Candidates for first alarms: 5xx error rate, ECS task restarts, RDS free storage, and ALB unhealthy host count.

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
infra/             Terraform (per-environment + modules)
tests/             Unit and integration tests
scripts/           entrypoint.sh, run_local.sh
```
