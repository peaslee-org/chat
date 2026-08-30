# IAM Roles & Policies

All roles are Terraform-managed (`infra/modules/*`). Names below are the `prod` ones.

## Runtime roles

| Role | Assumed by | Grants |
|---|---|---|
| `chat-api-prod-task` (ECS task role) | chat-api tasks | Inline policies: **bedrock** — `bedrock:InvokeModel`, `ListFoundationModels`, `ListInferenceProfiles`, `pricing:GetProducts`; **transcription** — S3 get/put/delete on the audio bucket + `ListBucket`, `sqs:SendMessage` (transcription queue), `transcribe:StartTranscriptionJob`, `ecs:RunTask` (transcription family) / `ecs:ListTasks` / `ecs:DescribeTasks` (cluster-scoped), `iam:PassRole` on the worker task/execution roles, `ecs:TagResource` (on RunTask), `ce:GetCostAndUsage` (for `/gpu/usage`); **photogrammetry** — `ecs:RunTask` (photogrammetry family) + PassRole/TagResource, `sqs:SendMessage` (photogrammetry queue); **exec-command** — `ssmmessages:*Channel` so `aws ecs execute-command` works. The same S3 grant covers the thumbnails the API writes under `…/thumbs/`. |
| `chat-api-prod-execution` | ECS agent for chat-api | `AmazonECSTaskExecutionRolePolicy` + `secretsmanager:GetSecretValue` on the database-url and LangSmith secrets |
| `transcription-prod-worker-task` | transcription worker tasks (EC2 launch type) | SQS receive/delete/change-visibility/get-attributes, S3 get/put on the audio bucket + `ListBucket`, `transcribe:GetTranscriptionJob`, `cloudwatch:PutMetricData`, `secretsmanager:GetSecretValue` (HF token) |
| `transcription-prod-worker-execution` | ECS agent for the transcription worker | ECR pull, logs, HF-token secret |
| `photogrammetry-prod-worker-task` | photogrammetry worker tasks | SQS receive/delete/change-visibility/get-attributes (photogrammetry queue), S3 get/put + `ListBucket` on the audio bucket |
| `photogrammetry-prod-worker-execution` | ECS agent for the photogrammetry worker | ECR pull, logs, database-url secret |
| `gpu-prod-instance` (instance profile) | GPU EC2 instances | `AmazonEC2ContainerServiceforEC2Role` (ECS agent) + `AmazonSSMManagedInstanceCore` (Session Manager) |

The workers reach the database with the same `DATABASE_URL` secret as the API (worker execution roles read it).

## GitHub Actions (OIDC)

Provider `token.actions.githubusercontent.com`; each role trusts
`repo:<org>/<repo>:ref:refs/heads/main` (org/repo/branch are Terraform variables). No long-lived
keys anywhere in CI.

| Role | Workflow | Grants |
|---|---|---|
| `github-actions-prod` | `api.yml` | ECR auth + push to `chat-api`, `ecs:DescribeTaskDefinition` / `RegisterTaskDefinition` / `UpdateService` / `DescribeServices`, PassRole on the API task + execution roles |
| `github-actions-frontend-prod` | `vue.yml` | S3 sync to the frontend bucket, `cloudfront:CreateInvalidation` on the distribution |
| `transcription-prod-worker-github-actions` | `worker.yml` | ECR push to `transcription-worker-prod`, `ecs:DescribeTaskDefinition` / `RegisterTaskDefinition` / `TagResource`, PassRole on the worker roles — no service to update |
| `photogrammetry-prod-worker-github-actions` | `photogrammetry-worker.yml` | Same shape for `photogrammetry-prod-worker` |

The four workflows are reusable and called in dependency order by `deploy.yml` (ADR 005). Role
ARNs reach the workflows as repository secrets `AWS_DEPLOY_ROLE_ARN_{API,VUE,WORKER,PHOTOGRAMMETRY}`.

## Read-only review

Human review uses the AWS SSO `ReadOnlyAccess` permission set (local profile `claude-ro`);
`terraform plan -lock=false` works with it. Applies, bakes and manual ECS calls use an admin profile.
