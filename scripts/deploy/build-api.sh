#!/usr/bin/env bash
# Build and push the chat-api Docker image to ECR.
# Mirrors the build step in .github/workflows/api.yml for local/manual use.
#
# Usage:
#   ./scripts/deploy/build-api.sh                     # tag with git SHA + latest
#   ./scripts/deploy/build-api.sh --tag v1.2.3        # additional tag
#   ./scripts/deploy/build-api.sh --dry-run           # print docker commands without running

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"
ECR_REPO="chat-api"
DRY_RUN=false
EXTRA_TAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)     EXTRA_TAG="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    *)         echo "Usage: $0 [--tag <tag>] [--dry-run]"; exit 1 ;;
  esac
done

if [[ -z "$AWS_ACCOUNT_ID" ]]; then
  echo "Resolving AWS account ID..."
  AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
fi

REGISTRY="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
IMAGE_URI="$REGISTRY/$ECR_REPO"
GIT_SHA=$(git -C "$ROOT" rev-parse --short HEAD)

echo "=== Building chat-api ==="
echo "  Registry:  $REGISTRY"
echo "  Image:     $IMAGE_URI"
echo "  Tags:      $GIT_SHA, latest${EXTRA_TAG:+, $EXTRA_TAG}"
echo ""

run() {
  echo "  + $*"
  [[ "$DRY_RUN" == "false" ]] && "$@"
}

run aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

run docker build \
  -t "$IMAGE_URI:$GIT_SHA" \
  -t "$IMAGE_URI:latest" \
  ${EXTRA_TAG:+-t "$IMAGE_URI:$EXTRA_TAG"} \
  "$ROOT/chat-api"

run docker push "$IMAGE_URI:$GIT_SHA"
run docker push "$IMAGE_URI:latest"
[[ -n "$EXTRA_TAG" ]] && run docker push "$IMAGE_URI:$EXTRA_TAG"

echo ""
if [[ "$DRY_RUN" == "true" ]]; then
  echo "DRY RUN complete — no images were built or pushed."
else
  echo "Pushed: $IMAGE_URI:$GIT_SHA"
fi
