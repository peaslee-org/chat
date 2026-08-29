# Deploy Runbook

Everything ships from `main` via GitHub Actions (OIDC, no long-lived keys). Read-only checks use
`AWS_PROFILE=claude-ro`; anything that changes state (Terraform apply, AMI bake, manual ECS calls)
needs `AWS_PROFILE=neil-admin`. Region is `us-east-1`.

## Surfaces

| Change under… | Workflow | What it does | Live when… |
|---|---|---|---|
| `chat-api/` | `api.yml` | tests → ECR push (git-SHA tag) → ECS rolling deploy of service `chat-api-prod`. Alembic runs from `scripts/entrypoint.sh` before gunicorn binds, so migrations are part of the rollout. | `describe-services` shows one `PRIMARY` deployment, `rolloutState: COMPLETED` |
| `chat-vue/` | `vue.yml` | build → `s3 sync` to `chat-peaslee-frontend-prod` → CloudFront invalidation | invalidation done; hard-refresh `chat.peaslee.org` |
| `transcription-worker/`, `gpu-worker/` | `worker.yml` | ECR push → new task-def revision `transcription-prod-worker:N` | next `RunTask` picks it up (no service to roll) |
| `photogrammetry-worker/`, `gpu-worker/` | `photogrammetry-worker.yml` | same, family `photogrammetry-prod-worker` | same |
| `infra/` | `tf-validate.yml` (PR only) | fmt + validate. **Apply is manual.** | after your `terraform apply` |

Worker images are also baked into the GPU AMI so cold starts don't pull ~7 GB. A new worker image
is *usable* as soon as CI registers the revision, but each cold start pays a ~5 min pull until the
AMI is rebaked.

## Ordering rules

1. **Schema before readers.** If a worker's ORM model reads a new column, deploy the API (which
   migrates) before pushing the worker change — otherwise every SQS receipt raises outside the
   handler's try block and the message is never acked.
2. **API before Vue** when the UI depends on new fields (old API + new UI is usually a silent no-op;
   new API + old UI is always fine).
3. **Terraform before worker** when the task-def shape changes (volumes, env, memory). Terraform
   replaces the task-def with `photogrammetry_image_tag` / `image_tag` from `terraform.tfvars`, so
   set those to the *currently deployed* SHA first or the new revision points at `latest`.
4. **Batch worker-image changes** and bake once — a bake is ~20 min of GPU instance time.

Pushing one commit that touches several directories triggers all their workflows in parallel;
if ordering matters, push in separate commits/pushes and watch each finish.

## Steps

### API / Vue
```bash
git push origin main
gh run watch                # or: gh run list --limit 5
AWS_PROFILE=claude-ro aws ecs describe-services --cluster chat-api-prod --services chat-api-prod \
  --query 'services[0].deployments[].[status,rolloutState,taskDefinition]' --output text
```
Rollback: `git revert` and push. Migrations are forward-only; don't roll back past a schema change
without a down-migration in hand.

### Workers
```bash
git push origin main                                  # CI registers revision N
AWS_PROFILE=claude-ro aws ecs describe-task-definition --task-definition photogrammetry-prod-worker \
  --query 'taskDefinition.[revision,containerDefinitions[0].image]' --output text
```
Then bake, once per batch:
```bash
cd infra/environments/prod && AWS_PROFILE=neil-admin terraform output   # sg, instance profile
AWS_PROFILE=neil-admin BAKE_MARKET=on-demand ./scripts/deploy/build-gpu-ami.sh \
  <base-ami: gpu_ami_id in prod tfvars> \
  <ecr>/photogrammetry-prod-worker:<sha>,<ecr>/transcription-worker-prod:<sha> \
  <subnet-id> <gpu_security_group_id> <gpu_instance_profile_name>
```
Put the printed AMI id in `prod/terraform.tfvars` as `gpu_ami_id`, apply `prod` (launch-template
version bump only). The script keeps this AMI and the previous one and deregisters older ones.
The AMI name carries the UTC time, so same-day rebakes are fine.

Smoke after a worker deploy: run the sample scan (≈ 90 s on the GPU once the instance is up), then
whatever the change targets. Watch it with:
```bash
AWS_PROFILE=claude-ro ./scripts/deploy/gpu-status.sh
AWS_PROFILE=claude-ro aws logs tail /ecs/photogrammetry-prod-worker --since 30m --follow
```
Expect ~5 min instance start + (if not baked) ~5 min pull before the first log line. ECS managed
scaling often launches two instances for one task; the spare idles ~10 min then scales in.

### Infra
Two environments, applied separately. `prod` owns the API, frontend, Cognito, GPU capacity
(ASG / launch template / AMI). `transcription-prod` owns both worker task-defs, queues, and the
audio bucket.
```bash
cd infra/environments/<env>
terraform init -backend-config=backend.hcl
AWS_PROFILE=claude-ro  terraform plan  -lock=false      # read-only preview is fine with the RO profile
AWS_PROFILE=neil-admin terraform apply
```
A task-def "must be replaced" in the plan is normal whenever its shape changes — it registers a new
revision; nothing running is touched.

## Verify production state (5 min)
```bash
export AWS_PROFILE=claude-ro
gh run list --limit 10                                                     # every deploy green?
aws ecs describe-task-definition --task-definition chat-api-prod           --query 'taskDefinition.[revision,containerDefinitions[0].image]' --output text
aws ecs describe-task-definition --task-definition photogrammetry-prod-worker --query 'taskDefinition.[revision,containerDefinitions[0].image]' --output text
aws ecs describe-task-definition --task-definition transcription-prod-worker  --query 'taskDefinition.[revision,containerDefinitions[0].image]' --output text
aws s3api head-object --bucket chat-peaslee-frontend-prod --key index.html --query LastModified
./scripts/deploy/gpu-status.sh                                             # ASG 0/0 when idle
for q in photogrammetry-prod-dlq transcription-dlq-prod; do aws sqs get-queue-attributes \
  --queue-url "$(aws sqs get-queue-url --queue-name $q --query QueueUrl --output text)" \
  --attribute-names ApproximateNumberOfMessages --query Attributes --output text; done
(cd infra/environments/transcription-prod && terraform plan -lock=false | grep -E '^(Plan|No changes)')
(cd infra/environments/prod                && terraform plan -lock=false | grep -E '^(Plan|No changes)')
```
Image SHAs should be ancestors of `origin/main` (`git merge-base --is-ancestor <sha> origin/main`);
both plans should say `No changes` unless you know what's pending. Pending work, grouped by
surface, lives in `docs/TODO.md`. DLQ triage: `sqs-drain.md`.
