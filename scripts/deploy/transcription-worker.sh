#!/usr/bin/env bash
# Usage: transcription-worker.sh [start|stop|status|pause|unpause] [--no-status]
#
# Controls the transcription GPU worker (g4dn.xlarge Spot + ECS service).
# Requires AWS CLI configured with appropriate credentials.
#
# --no-status   Skip the automatic status check after start/stop/pause/unpause.

set -euo pipefail

ASG_NAME="transcription-prod-worker-gpu"
ECS_CLUSTER="chat-api-prod"
ECS_SERVICE="transcription-prod-worker"
NO_STATUS=false

for arg in "$@"; do
  [[ "$arg" == "--no-status" ]] && NO_STATUS=true
done

# Resolved once at runtime from the ECS task definition (avoids hardcoding account ID).
# Task definition family and ECS service share the same name.
get_audio_bucket() {
  aws ecs describe-task-definition \
    --task-definition "$ECS_SERVICE" \
    --query "taskDefinition.containerDefinitions[0].environment[?name=='AUDIO_BUCKET_NAME'].value" \
    --output text 2>/dev/null || true
}

usage() {
  echo "Usage: $0 [start|stop|status|pause|unpause] [--no-status]"
  exit 1
}

status() {
  echo "=== ASG ==="
  aws autoscaling describe-auto-scaling-groups \
    --auto-scaling-group-names "$ASG_NAME" \
    --query "AutoScalingGroups[0].{Desired:DesiredCapacity,Min:MinSize,Max:MaxSize,Instances:Instances[*].{Id:InstanceId,State:LifecycleState,Health:HealthStatus}}" \
    --output table

  echo ""
  echo "=== ECS Service ==="
  aws ecs describe-services \
    --cluster "$ECS_CLUSTER" \
    --services "$ECS_SERVICE" \
    --query "services[0].{Status:status,Desired:desiredCount,Running:runningCount,Pending:pendingCount}" \
    --output table

  echo ""
  echo "=== SQS Queue depth ==="
  QUEUE_URL=$(aws sqs get-queue-url --queue-name "transcription-prod" --query QueueUrl --output text)
  aws sqs get-queue-attributes \
    --queue-url "$QUEUE_URL" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query "Attributes" \
    --output table

  echo ""
  echo "=== UI pause flag ==="
  BUCKET=$(get_audio_bucket)
  if [[ -n "$BUCKET" ]]; then
    FLAG=$(aws s3 cp "s3://${BUCKET}/worker_paused" - 2>/dev/null | tr -d '[:space:]' || echo "")
    if [[ "$FLAG" == "true" ]]; then
      echo "  PAUSED — users see 'service paused' in the UI"
    else
      echo "  not paused — users see normal status"
    fi
  else
    echo "  (could not resolve bucket name)"
  fi
}

maybe_status() {
  if [[ "$NO_STATUS" == "false" ]]; then
    echo ""
    echo "=== Current status ==="
    status
  fi
}

start() {
  echo "Starting transcription worker..."

  BUCKET=$(get_audio_bucket)
  if [[ -n "$BUCKET" ]]; then
    printf "false" | aws s3 cp - "s3://${BUCKET}/worker_paused" --quiet
    echo "  S3 paused flag set to false (users will see normal status)"
  fi

  aws autoscaling set-desired-capacity \
    --auto-scaling-group-name "$ASG_NAME" \
    --desired-capacity 1
  echo "  ASG desired capacity -> 1"

  aws ecs update-service \
    --cluster "$ECS_CLUSTER" \
    --service "$ECS_SERVICE" \
    --desired-count 1 \
    --output json > /dev/null
  echo "  ECS service desired count -> 1"

  echo ""
  echo "Note: allow ~3-5 min for EC2 boot + container start."
  maybe_status
}

stop() {
  echo "Stopping transcription worker..."

  aws ecs update-service \
    --cluster "$ECS_CLUSTER" \
    --service "$ECS_SERVICE" \
    --desired-count 0 \
    --output json > /dev/null
  echo "  ECS service desired count -> 0"

  aws autoscaling set-desired-capacity \
    --auto-scaling-group-name "$ASG_NAME" \
    --desired-capacity 0
  echo "  ASG desired capacity -> 0"

  BUCKET=$(get_audio_bucket)
  if [[ -n "$BUCKET" ]]; then
    printf "true" | aws s3 cp - "s3://${BUCKET}/worker_paused" --quiet
    echo "  S3 paused flag set to true (users will see 'service paused' in the UI)"
  fi

  echo ""
  echo "Note: SQS messages are retained for 24 hours — queued jobs will process when restarted."
  maybe_status
}

pause() {
  echo "Setting UI pause flag (infrastructure unchanged)..."

  BUCKET=$(get_audio_bucket)
  if [[ -z "$BUCKET" ]]; then
    echo "Error: could not resolve AUDIO_BUCKET_NAME from task definition" >&2
    exit 1
  fi

  printf "true" | aws s3 cp - "s3://${BUCKET}/worker_paused" --quiet
  echo "  S3 paused flag set to true (users will see 'service paused' in the UI)"
  maybe_status
}

unpause() {
  echo "Clearing UI pause flag (infrastructure unchanged)..."

  BUCKET=$(get_audio_bucket)
  if [[ -z "$BUCKET" ]]; then
    echo "Error: could not resolve AUDIO_BUCKET_NAME from task definition" >&2
    exit 1
  fi

  printf "false" | aws s3 cp - "s3://${BUCKET}/worker_paused" --quiet
  echo "  S3 paused flag set to false (users will see normal status)"
  maybe_status
}

case "${1:-}" in
  start)   start ;;
  stop)    stop ;;
  status)  status ;;
  pause)   pause ;;
  unpause) unpause ;;
  *)       usage ;;
esac
