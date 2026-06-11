#!/usr/bin/env bash
set -euo pipefail

PYTHON=/app/.venv/bin/python

echo "[entrypoint] $(${PYTHON} --version)"

echo "[entrypoint] Running database migrations..."
"${PYTHON}" -m alembic -c /app/app/db/alembic.ini upgrade head

echo "[entrypoint] Starting server..."
exec "${PYTHON}" -m gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers "${GUNICORN_WORKERS:-2}" \
    --bind "0.0.0.0:${PORT:-8000}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
