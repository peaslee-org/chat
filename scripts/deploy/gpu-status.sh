#!/usr/bin/env bash
# One-screen GPU pool status: ASG, worker tasks, queue depth, open ledger sessions (via the API if given).
set -euo pipefail
ENV=${1:-prod}; REGION=${AWS_REGION:-us-east-1}
CLUSTER="chat-api-${ENV}"; ASG="gpu-${ENV}"; FAMILY="transcription-${ENV}-worker"
echo "== ASG $ASG"; aws autoscaling describe-auto-scaling-groups --region "$REGION" --auto-scaling-group-names "$ASG" \
  --query 'AutoScalingGroups[0].[MinSize,DesiredCapacity,MaxSize,length(Instances)]' --output text
echo "== worker tasks"; ARNS=$(aws ecs list-tasks --region "$REGION" --cluster "$CLUSTER" --family "$FAMILY" --query taskArns --output text)
[[ -n "$ARNS" && "$ARNS" != None ]] && aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks $ARNS \
  --query 'tasks[].[lastStatus,startedBy,createdAt]' --output text || echo "none"
echo "== queue"; aws sqs get-queue-attributes --region "$REGION" --queue-url "https://sqs.${REGION}.amazonaws.com/$(aws sts get-caller-identity --query Account --output text)/transcription-${ENV}" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --query Attributes --output text
