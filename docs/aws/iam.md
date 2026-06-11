# IAM Roles & Policies

| Role | Assumed By | Key Policies |
|---|---|---|
| `transcription-prod-worker-github-actions` | GitHub Actions OIDC | ECR push, ECS deploy, ECS describe |
| ECS Task Role — chat-api | chat-api ECS tasks | Bedrock InvokeModel, S3 (audio bucket), SQS SendMessage, Transcribe StartJob, Cognito (JWKS read), Secrets Manager |
| ECS Task Role — transcription-worker | transcription-worker ECS tasks | SQS (receive/delete/change-visibility), S3 (audio bucket read/write), Transcribe GetJob, Secrets Manager GetSecretValue (HF token), CloudWatch PutMetricData |

## GitHub Actions OIDC

- Provider: `token.actions.githubusercontent.com`
- Trust condition: `repo:YOUR_ORG/YOUR_REPO:ref:refs/heads/main`
- Defined in: `infra/modules/github-oidc/`
