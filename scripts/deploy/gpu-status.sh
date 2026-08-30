#!/usr/bin/env bash
# One-screen GPU pool status: ASG, worker tasks, queue depth. Live worker debugging is SSM to
# the instance this prints, not the API (enableExecuteCommand went with the RunTask service).
set -euo pipefail
ENV=${1:-prod}; REGION=${AWS_REGION:-us-east-1}
CLUSTER="chat-api-${ENV}"; ASG_NAME_TAG="gpu-${ENV}"
echo "== ASG $ASG_NAME_TAG"; aws autoscaling describe-auto-scaling-groups --region "$REGION" \
  --filters "Name=tag:Name,Values=${ASG_NAME_TAG}" \
  --query 'AutoScalingGroups[0].[AutoScalingGroupName,MinSize,DesiredCapacity,MaxSize,length(Instances)]' --output text
echo "== worker tasks"; ARNS=$(for FAMILY in "transcription-${ENV}-worker" "photogrammetry-${ENV}-worker"; do
  aws ecs list-tasks --region "$REGION" --cluster "$CLUSTER" --family "$FAMILY" --query taskArns --output text; done | tr '\t' '\n' | grep -v '^None$' || true)
[[ -n "$ARNS" ]] && aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks $ARNS \
  --query 'tasks[].[lastStatus,startedBy,createdAt,taskDefinitionArn]' --output text | sed 's#arn:aws:ecs:[^ ]*task-definition/##' || echo "none"
echo "== queue"; aws sqs get-queue-attributes --region "$REGION" --queue-url "https://sqs.${REGION}.amazonaws.com/$(aws sts get-caller-identity --query Account --output text)/transcription-${ENV}" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --query Attributes --output text
