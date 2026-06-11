#!/bin/bash
# GPU worker helper — start/stop/ssh into the transcription spot worker (ASG-managed g4dn.xlarge).
#
# Usage:
#   ./scripts/local/gpu-dev.sh start   — set ASG desired capacity to 1 and wait for the instance
#   ./scripts/local/gpu-dev.sh stop    — set ASG desired capacity to 0 (terminates spot instance)
#   ./scripts/local/gpu-dev.sh ssh     — open SSM session on the running instance
#   ./scripts/local/gpu-dev.sh status  — print ASG + instance state
#
# Prerequisites: AWS CLI configured with appropriate credentials, SSM Session Manager plugin installed.

set -euo pipefail

ASG_NAME="${GPU_ASG_NAME:-transcription-prod-worker-gpu}"
REGION="${AWS_REGION:-$(aws configure get region 2>/dev/null)}"
REGION="${REGION:-us-east-1}"

get_instance_id() {
  aws autoscaling describe-auto-scaling-groups \
    --auto-scaling-group-names "$ASG_NAME" \
    --region "$REGION" \
    --query 'AutoScalingGroups[0].Instances[?LifecycleState==`InService`].InstanceId' \
    --output text 2>/dev/null | awk '{print $1}'
}


case "${1:-}" in
  start)
    echo "Setting ASG desired capacity to 1 …"
    aws autoscaling set-desired-capacity \
      --auto-scaling-group-name "$ASG_NAME" \
      --desired-capacity 1 \
      --region "$REGION"
    echo "Waiting for instance to reach InService …"
    until INSTANCE_ID="$(get_instance_id)" && [[ -n "$INSTANCE_ID" && "$INSTANCE_ID" != "None" ]]; do
      sleep 5
    done
    echo "Waiting for instance-running …"
    aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"
    echo "Ready — $INSTANCE_ID"
    ;;
  stop)
    echo "Setting ASG desired capacity to 0 (spot instance will terminate) …"
    aws autoscaling set-desired-capacity \
      --auto-scaling-group-name "$ASG_NAME" \
      --desired-capacity 0 \
      --region "$REGION"
    echo "Stop initiated."
    ;;
  ssh)
    INSTANCE_ID="$(get_instance_id)"
    if [[ -z "$INSTANCE_ID" || "$INSTANCE_ID" == "None" ]]; then
      echo "ERROR: no InService instance in ASG '${ASG_NAME}' — run: $0 start"
      exit 1
    fi
    echo "Opening SSM session on $INSTANCE_ID …"
    exec aws ssm start-session --target "$INSTANCE_ID" --region "$REGION" \
      --document-name AWS-StartInteractiveCommand \
      --parameters '{"command":["bash -l"]}'
    ;;
  status)
    echo "=== ASG ==="
    aws autoscaling describe-auto-scaling-groups \
      --auto-scaling-group-names "$ASG_NAME" \
      --region "$REGION" \
      --query "AutoScalingGroups[0].{Desired:DesiredCapacity,Min:MinSize,Max:MaxSize,Instances:Instances[*].{Id:InstanceId,State:LifecycleState,Health:HealthStatus}}" \
      --output table
    ;;
  *)
    echo "Usage: $0 {start|stop|ssh|status}"
    exit 1
    ;;
esac
