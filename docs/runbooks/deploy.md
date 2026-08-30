# Deploy Runbook

Everything ships from `main` via GitHub Actions (OIDC, no long-lived keys). Read-only checks use
`AWS_PROFILE=claude-ro`; anything that changes state (Terraform apply, AMI bake, manual ECS calls)
needs `AWS_PROFILE=neil-admin`. Region is `us-east-1`.

## Surfaces

`deploy.yml` runs on every push to `main`: a `changes` job detects which directories the push
touched, then runs the surfaces it needs **in dependency order** — `chat-api` first (it carries
the Alembic migration), then `chat-vue` and both workers. A surface with no changes is skipped and
doesn't hold the others; a failed API deploy stops them. Each surface is its own reusable workflow.

| Change under… | Reusable workflow | What it does | Live when… |
|---|---|---|---|
| `chat-api/` | `api.yml` | tests → ECR push (git-SHA tag) → ECS rolling deploy of service `chat-api-prod`. Alembic runs from `scripts/entrypoint.sh` before gunicorn binds, so migrations are part of the rollout. | `describe-services` shows one `PRIMARY` deployment, `rolloutState: COMPLETED` |
| `chat-vue/` | `vue.yml` | build → `s3 sync` to the frontend bucket → CloudFront invalidation | invalidation done; hard-refresh the site |
| `transcription-worker/`, `gpu-worker/` | `worker.yml` | ECR push → new task-def revision `transcription-prod-worker:N` | next `RunTask` picks it up (no service to roll) |
| `photogrammetry-worker/`, `gpu-worker/` | `photogrammetry-worker.yml` | same, family `photogrammetry-prod-worker` | same |
| `infra/` | `tf-validate.yml` (PR only) | fmt + validate. **Apply is manual.** | after your `terraform apply` |

Manual redeploy of one surface without a code change: **Actions → Deploy → Run workflow** and tick
the surface (`gh workflow run Deploy -f photogrammetry_worker=true`). Deploys queue behind each
other (`concurrency: deploy-prod`, never cancelled).

**If the API job fails**, the surfaces behind it are *skipped, not retried*. A fix that touches
only `chat-api/` redeploys only the API — the skipped surfaces stay on their old build until you
dispatch them: `gh workflow run Deploy -f vue=true` (queues behind the running deploy). ECS keeps
the previous task set serving while a new revision crash-loops, so a failed API rollout is
"stuck", not "down"; the API log (`/ecs/chat-api-prod`) has the traceback.

Worker images are also baked into the GPU AMI so cold starts don't pull ~7 GB. A new worker image
is *usable* as soon as CI registers the revision, but each cold start pays a ~5 min pull until the
AMI is rebaked.

## Ordering rules

1. **Schema before readers** — enforced by `deploy.yml` (API job first). Why it matters: a worker
   whose ORM model reads a column that doesn't exist yet raises outside the handler's try block on
   every SQS receipt and never acks. Still your job when deploying by hand.
2. **API before Vue** — also enforced by `deploy.yml`. Old API + new UI is usually a silent no-op;
   new API + old UI is always fine.
3. **Terraform before worker** when the task-def shape changes (volumes, env, memory). Terraform
   replaces the task-def with `photogrammetry_image_tag` / `image_tag` from `terraform.tfvars`, so
   set those to the *currently deployed* SHA first or the new revision points at `latest`.
4. **Batch worker-image changes** and bake once — a bake is ~20 min of GPU instance time.
5. **Worker Python deps are pinned** by each worker's `constraints.txt` (a `pip freeze` of the image
   that passed acceptance). A rebuild reproduces that image; to upgrade a package, edit the pin — and
   re-freeze from the new image once it has passed a smoke, so the file stays a record of what ran.

One push that touches several directories is fine — `deploy.yml` orders them. Rule 3 is the one
it can't enforce: apply Terraform before pushing a worker change that needs the new task-def shape.

## Steps

### API / Vue
```bash
git push origin main
gh run watch                # the single Deploy run; or: gh run list --limit 5
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
