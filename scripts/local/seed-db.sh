#!/usr/bin/env bash
# Seed the local development database with test data.
# Requires the chat-api Docker Compose stack to be running (docker compose up).
#
# Usage:
#   ./scripts/local/seed-db.sh                       # uses default test user sub
#   ./scripts/local/seed-db.sh --user-sub <sub>      # use a specific Cognito sub

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
USER_SUB="dev-user-00000000-0000-0000-0000-000000000001"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user-sub) USER_SUB="$2"; shift 2 ;;
    *) echo "Usage: $0 [--user-sub <sub>]"; exit 1 ;;
  esac
done

# Verify the postgres container is up
if ! docker compose -f "$ROOT/chat-api/docker-compose.yml" ps postgres 2>/dev/null | grep -q "running"; then
  echo "ERROR: postgres container is not running."
  echo "  Start it with: cd chat-api && docker compose up -d"
  exit 1
fi

echo "Seeding dev database (user_sub=$USER_SUB)..."

docker compose -f "$ROOT/chat-api/docker-compose.yml" exec postgres psql \
  -U postgres -d chatapi -v ON_ERROR_STOP=1 <<SQL
-- Remove existing seed data for this user (idempotent re-run)
DELETE FROM messages       WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id = '$USER_SUB');
DELETE FROM conversations  WHERE user_id = '$USER_SUB';
DELETE FROM speaker_samples WHERE speaker_profile_id IN (SELECT id FROM speaker_profiles WHERE user_id = '$USER_SUB');
DELETE FROM speaker_profiles WHERE user_id = '$USER_SUB';

-- Conversations + messages
INSERT INTO conversations (id, user_id, title, model_id, created_at, updated_at)
VALUES
  ('00000000-0000-0000-0001-000000000001', '$USER_SUB', 'What is pgvector?',
   'anthropic.claude-3-sonnet-20240229-v1:0', now() - interval '2 days', now() - interval '2 days'),
  ('00000000-0000-0000-0001-000000000002', '$USER_SUB', 'Explain pyannote diarization',
   'anthropic.claude-3-sonnet-20240229-v1:0', now() - interval '1 day',  now() - interval '1 day');

INSERT INTO messages (id, conversation_id, role, content, created_at)
VALUES
  ('00000000-0000-0000-0002-000000000001', '00000000-0000-0000-0001-000000000001',
   'user',      'What is pgvector and when should I use it?', now() - interval '2 days'),
  ('00000000-0000-0000-0002-000000000002', '00000000-0000-0000-0001-000000000001',
   'assistant', 'pgvector is a PostgreSQL extension that adds a vector data type and similarity search operators...', now() - interval '2 days'),
  ('00000000-0000-0000-0002-000000000003', '00000000-0000-0000-0001-000000000002',
   'user',      'How does pyannote speaker diarization work?', now() - interval '1 day'),
  ('00000000-0000-0000-0002-000000000004', '00000000-0000-0000-0001-000000000002',
   'assistant', 'pyannote-audio is a neural network toolkit for speaker diarization...', now() - interval '1 day');

-- Speaker profiles (no embeddings — samples require real audio)
INSERT INTO speaker_profiles (id, user_id, speaker_name, created_at, updated_at)
VALUES
  ('00000000-0000-0000-0003-000000000001', '$USER_SUB', 'Alice Dev', now(), now()),
  ('00000000-0000-0000-0003-000000000002', '$USER_SUB', 'Bob Dev',   now(), now());

SELECT 'Seeded: ' || count(*) || ' conversations' FROM conversations WHERE user_id = '$USER_SUB';
SELECT 'Seeded: ' || count(*) || ' messages'      FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id = '$USER_SUB');
SELECT 'Seeded: ' || count(*) || ' speaker profiles' FROM speaker_profiles WHERE user_id = '$USER_SUB';
SQL

echo ""
echo "Done. Sign in with Cognito sub '$USER_SUB' to see the seeded data."
echo "Note: speaker samples require real audio — seed them via the UI or API."
