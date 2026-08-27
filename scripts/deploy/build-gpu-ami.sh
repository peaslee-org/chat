#!/usr/bin/env bash
# Bake worker images into the ECS GPU base AMI so a cold start pulls nothing.
# Usage: AWS_PROFILE=<admin> scripts/deploy/build-gpu-ami.sh <base-ami> <image-uri:tag>[,<image-uri:tag>…] <subnet-id> <sg-id> <instance-profile> [env]
# Prints the new AMI id last. Keeps this AMI and the previous one; deregisters older ones (+ snapshots).
set -euo pipefail
BASE_AMI=$1; IMAGES=$2; IFS=',' read -r -a IMAGE_LIST <<< "$IMAGES"; IMAGE=${IMAGE_LIST[0]}; SUBNET=$3; SG=$4; PROFILE=$5; ENV=${6:-prod}
REGION=${AWS_REGION:-us-east-1}
TAG=${IMAGE##*:}; NAME="gpu-${ENV}-$(date -u +%Y%m%d)-${TAG:0:7}"
REGISTRY=${IMAGE%%/*}

USERDATA=$(cat <<EOS
#!/bin/bash
set -e
aws ecr get-login-password --region ${REGION} | docker login --username AWS --password-stdin ${REGISTRY}
for IMG in ${IMAGE_LIST[*]}; do docker pull \$IMG; done
systemctl stop ecs
rm -rf /var/lib/ecs/data/*
touch /var/tmp/bake-done
EOS
)
echo "Launching bake instance from ${BASE_AMI} …"
IID=$(aws ec2 run-instances --region "$REGION" --image-id "$BASE_AMI" --instance-type g4dn.xlarge \
  --subnet-id "$SUBNET" --security-group-ids "$SG" --iam-instance-profile "Name=$PROFILE" \
  --instance-market-options 'MarketType=spot' \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":80,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
  --metadata-options 'HttpTokens=required,HttpPutResponseHopLimit=2' \
  --user-data "$USERDATA" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME}-bake},{Key=CostCenter,Value=gpu}]" \
  --query 'Instances[0].InstanceId' --output text)
trap 'echo "Terminating $IID"; aws ec2 terminate-instances --region "$REGION" --instance-ids "$IID" >/dev/null' EXIT
aws ec2 wait instance-status-ok --region "$REGION" --instance-ids "$IID"
echo "Waiting for docker pull (SSM) …"
for _ in $(seq 1 60); do
  CID=$(aws ssm send-command --region "$REGION" --instance-ids "$IID" --document-name AWS-RunShellScript \
        --parameters 'commands=["test -f /var/tmp/bake-done && echo done || echo wait"]' --query Command.CommandId --output text)
  sleep 20
  OUT=$(aws ssm get-command-invocation --region "$REGION" --command-id "$CID" --instance-id "$IID" --query StandardOutputContent --output text 2>/dev/null || echo wait)
  [[ "$OUT" == *done* ]] && break
done
[[ "$OUT" == *done* ]] || { echo "bake did not finish in 20 min"; exit 1; }
# One-time spot instances cannot be stopped; create-image on the running instance reboots it
# for a consistent snapshot (the ECS agent is already stopped and its state cleared by user-data).
# tag value: '/' and ',' → '_' (shorthand syntax treats ',' as a delimiter)
AMI=$(aws ec2 create-image --region "$REGION" --instance-id "$IID" --name "$NAME" \
  --tag-specifications "ResourceType=image,Tags=[{Key=Name,Value=$NAME},{Key=CostCenter,Value=gpu},{Key=Image,Value=${IMAGES//[\/,]/_}}]" \
  --query ImageId --output text)
# `aws ec2 wait image-available` gives up after 10 min; an 80 GB root snapshot can take longer.
echo "Waiting for $AMI to become available (up to 40 min) …"
for _ in $(seq 1 160); do
  STATE=$(aws ec2 describe-images --region "$REGION" --image-ids "$AMI" --query 'Images[0].State' --output text)
  [[ "$STATE" == available ]] && break
  [[ "$STATE" == failed ]] && { echo "AMI $AMI failed"; exit 1; }
  sleep 15
done
[[ "$STATE" == available ]] || { echo "AMI $AMI still $STATE after 40 min — it may finish on its own; check before re-running"; exit 1; }
# prune: keep the two newest gpu-<env>-* AMIs
for OLD in $(aws ec2 describe-images --region "$REGION" --owners self --filters "Name=name,Values=gpu-${ENV}-*" \
             --query 'sort_by(Images,&CreationDate)[:-2].ImageId' --output text); do
  SNAPS=$(aws ec2 describe-images --region "$REGION" --image-ids "$OLD" --query 'Images[0].BlockDeviceMappings[].Ebs.SnapshotId' --output text)
  aws ec2 deregister-image --region "$REGION" --image-id "$OLD"
  for S in $SNAPS; do aws ec2 delete-snapshot --region "$REGION" --snapshot-id "$S"; done
  echo "Pruned $OLD"
done
echo "New AMI: $AMI  → set gpu_ami_id in your prod tfvars and apply."
echo "$AMI"
