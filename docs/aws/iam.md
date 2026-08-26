# IAM Roles & Policies

| Role | Assumed By | Key Policies |
|---|---|---|
| `transcription-prod-worker-github-actions` | GitHub Actions OIDC | ECR push, ECS register-task-definition, ECS describe (no ECS deploy — `worker.yml` only registers a task-definition revision; there's no service to roll) |
| ECS Task Role — chat-api | chat-api ECS tasks | Bedrock InvokeModel, S3 (audio bucket), SQS SendMessage, Transcribe StartJob, Cognito (JWKS read), Secrets Manager, `ecs:RunTask` / `ecs:ListTasks` / `ecs:DescribeTasks` (cluster-scoped, to launch and poll the GPU worker), `iam:PassRole` on the worker's task/execution roles, `ce:GetCostAndUsage` (for `/gpu/usage`) |
| ECS Task Role — transcription-worker | transcription-worker ECS tasks (EC2 launch type, GPU capacity provider) | SQS (receive/delete/change-visibility), S3 (audio bucket read/write), Transcribe GetJob, Secrets Manager GetSecretValue (HF token), CloudWatch PutMetricData |

## GitHub Actions OIDC

- Provider: `token.actions.githubusercontent.com`
- Trust condition: `repo:YOUR_ORG/YOUR_REPO:ref:refs/heads/main`
- Defined in: `infra/modules/github-oidc/`
