# Secrets Manager

*Names only — no values stored here.*

| Secret Name (Terraform var) | Contents | Consumed By |
|---|---|---|
| `huggingface_token_secret_arn` | HuggingFace read token for pyannote gated model | transcription-worker ECS task (env injection at startup) |
| (see chat-api task def) | `DATABASE_URL` | chat-api ECS task |

## Local Dev

Copy `.env.example` in each sub-project and fill in values locally. Never commit `.env` files.

GitHub Actions secrets required:
- `HUGGINGFACE_TOKEN` — used as `--build-arg` during Docker image build for transcription-worker
