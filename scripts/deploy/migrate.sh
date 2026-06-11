#!/usr/bin/env bash
# Run Alembic migrations against the production database via ECS exec.
#
# RDS is in a private VPC with no direct inbound access. This script finds
# the running chat-api task and runs `alembic upgrade head` inside the
# container, using the DATABASE_URL already present in the task environment.
#
# Prerequisites:
#   - AWS CLI configured with sufficient permissions (ecs:ExecuteCommand, ssm:*)
#   - SSM Session Manager plugin installed:
#       https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html
#   - ECS exec enabled on the service (enable_execute_command = true in Terraform)
#
# Usage:
#   ./scripts/deploy/migrate.sh
#   ./scripts/deploy/migrate.sh --dry-run   # print the command without executing

set -euo pipefail

CLUSTER="${ECS_CLUSTER:-chat-api-prod}"
SERVICE="${ECS_SERVICE:-chat-api-prod}"
CONTAINER="${ECS_CONTAINER:-chat-api}"
DRY_RUN=false

for arg in "$@"; do
  [[ "$arg" == "--dry-run" ]] && DRY_RUN=true
done

echo "=== Alembic migration via ECS exec ==="
echo "  Cluster:   $CLUSTER"
echo "  Service:   $SERVICE"
echo "  Container: $CONTAINER"
echo ""

echo "Finding running task..."
TASK=$(aws ecs list-tasks \
  --cluster "$CLUSTER" \
  --service-name "$SERVICE" \
  --desired-status RUNNING \
  --query "taskArns[0]" \
  --output text)

if [[ -z "$TASK" || "$TASK" == "None" ]]; then
  echo "ERROR: no running tasks found in $SERVICE" >&2
  echo "  Start the service first, or check:" >&2
  echo "    aws ecs describe-services --cluster $CLUSTER --services $SERVICE" >&2
  exit 1
fi

echo "  Task: $TASK"
echo ""

CMD="uv run alembic -c app/db/alembic.ini upgrade head"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "DRY RUN — would execute:"
  echo "  aws ecs execute-command --cluster $CLUSTER --task $TASK --container $CONTAINER --interactive --command \"$CMD\""
  exit 0
fi

echo "Running: $CMD"
echo "--- output ---"
aws ecs execute-command \
  --cluster "$CLUSTER" \
  --task "$TASK" \
  --container "$CONTAINER" \
  --interactive \
  --command "$CMD"
