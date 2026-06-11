#!/usr/bin/env bash
# First-time dev environment setup.
# Installs dependencies and copies .env.example files for all sub-projects.
#
# Usage: ./scripts/local/setup.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

check_cmd() {
  if ! command -v "$1" &>/dev/null; then
    echo "  MISSING: $1 — $2"
    MISSING=true
  else
    echo "  OK:      $1"
  fi
}

echo "=== Checking prerequisites ==="
MISSING=false
check_cmd docker   "https://docs.docker.com/get-docker/"
check_cmd uv       "curl -LsSf https://astral.sh/uv/install.sh | sh"
check_cmd npm      "https://nodejs.org/ (use nvm for version management)"
check_cmd aws      "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
check_cmd terraform "https://developer.hashicorp.com/terraform/install"

if [[ "$MISSING" == "true" ]]; then
  echo ""
  echo "Install the missing tools above and re-run this script."
  exit 1
fi

echo ""
echo "=== chat-api ==="
cd "$ROOT/chat-api"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "  Created chat-api/.env (fill in values before running)"
else
  echo "  .env already exists — skipping"
fi
echo "  Installing Python dependencies..."
uv sync
echo "  Done."

echo ""
echo "=== chat-vue ==="
cd "$ROOT/chat-vue"
if [[ ! -f .env.local ]]; then
  cp .env.example .env.local
  echo "  Created chat-vue/.env.local (fill in Cognito values before running)"
else
  echo "  .env.local already exists — skipping"
fi
echo "  Installing Node dependencies..."
npm install
echo "  Done."

echo ""
echo "=== transcription-worker ==="
cd "$ROOT/transcription-worker"
if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "  Created transcription-worker/.env (fill in values before running)"
  else
    echo "  No .env.example found — skipping (not needed unless running worker locally)"
  fi
else
  echo "  .env already exists — skipping"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Fill in chat-api/.env       — DATABASE_URL, COGNITO_*, AWS_* required"
echo "  2. Fill in chat-vue/.env.local — VITE_COGNITO_*, VITE_API_BASE_URL required"
echo "  3. Start the API + DB:  cd chat-api && docker compose up"
echo "  4. Start the frontend:  cd chat-vue && npm run dev"
echo ""
echo "See each sub-directory's CLAUDE.md for full dev instructions."
