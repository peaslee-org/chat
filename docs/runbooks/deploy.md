# Deploy Runbook

## chat-api

Push to `main` → CodePipeline runs `buildspec.yml` → ECR push → ECS rolling deploy.

Manual deploy:
```bash
cd chat-api
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 123456789012.dkr.ecr.us-east-1.amazonaws.com
docker build -t chat-api-prod .
docker tag chat-api-prod:latest 123456789012.dkr.ecr.us-east-1.amazonaws.com/chat-api-prod:latest
docker push 123456789012.dkr.ecr.us-east-1.amazonaws.com/chat-api-prod:latest
aws ecs update-service --cluster chat-api-prod --service chat-api-prod --force-new-deployment
```

## transcription-worker

Push to `main` → GitHub Actions `worker.yml` → ECR push → ECS rolling deploy (automatic via OIDC).

### Capturing fixtures from production

Set `DEV_CAPTURE_FIXTURES_S3_PREFIX=dev-fixtures` in the task definition (already set in Terraform) to write pipeline output to S3 after each job. Download with:

```bash
aws s3 cp --recursive s3://chat-audio-prod-123456789012/dev-fixtures/<job_id>/ ./fixtures/<job_id>/
```

Fixtures can be replayed locally via `dev_worker.py` without ML models. See [docs/mock-api.md](../mock-api.md) for details.

To stop capturing, remove `DEV_CAPTURE_FIXTURES_S3_PREFIX` from the Terraform env block and apply.

## chat-vue

```bash
cd chat-vue
npm run build
aws s3 sync dist/ s3://<BUCKET_NAME>/ --delete
aws cloudfront create-invalidation --distribution-id <DIST_ID> --paths "/*"
```

## DB Migrations

```bash
# Via ECS exec (production)
TASK=$(aws ecs list-tasks --cluster chat-api-prod --query "taskArns[0]" --output text)
aws ecs execute-command --cluster chat-api-prod --task "$TASK" \
  --container chat-api --interactive \
  --command "uv run alembic -c app/db/alembic.ini upgrade head"
```
