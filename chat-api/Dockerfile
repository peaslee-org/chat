# syntax=docker/dockerfile:1

# ── builder ───────────────────────────────────────────────────────────────────
# Pin both stages to the same digest so compiled C extensions are compatible.
FROM python:3.12-slim AS builder

# Pin uv to a specific version for reproducible builds.
COPY --from=ghcr.io/astral-sh/uv:0.6.6 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install deps before copying source — layer cache stays valid on code changes.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

# Install the local package itself.
COPY app ./app
RUN uv sync --frozen --no-dev

# ── runtime ───────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN addgroup --system app && adduser --system --ingroup app app

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Both stages share the same base image, so libc versions match and the
# venv's compiled binaries are safe to copy across.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app   /app/app
COPY scripts/entrypoint.sh     /app/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN chmod +x /app/entrypoint.sh

USER app
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
