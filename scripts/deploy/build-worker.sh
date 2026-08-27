#!/usr/bin/env bash
# Build and push the transcription-worker Docker image to ECR.
# Mirrors the build step in .github/workflows/worker.yml for local/manual use.
#
# The HuggingFace token is required at build time to download the pyannote
# gated model into the image. It is NOT baked into the final image layer —
# Docker uses it only during the download step.
#
# Usage:
#   HUGGINGFACE_TOKEN=hf_xxx ./scripts/deploy/build-worker.sh
#   ./scripts/deploy/build-worker.sh --tag v1.2.3
#   ./scripts/deploy/build-worker.sh --dry-run

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"
ECR_REPO="transcription-worker-prod"
HF_TOKEN="${HUGGINGFACE_TOKEN:-}"
DRY_RUN=false
EXTRA_TAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)     EXTRA_TAG="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    *)         echo "Usage: HUGGINGFACE_TOKEN=hf_xxx $0 [--tag <tag>] [--dry-run]"; exit 1 ;;
  esac
done

if [[ -z "$HF_TOKEN" ]] && [[ "$DRY_RUN" == "false" ]]; then
  echo "ERROR: HUGGINGFACE_TOKEN is required to download the pyannote model at build time."
  echo "  Export it: export HUGGINGFACE_TOKEN=hf_..."
  echo "  Or run:    HUGGINGFACE_TOKEN=hf_xxx $0"
  exit 1
fi

if [[ -z "$AWS_ACCOUNT_ID" ]] && [[ "$DRY_RUN" == "false" ]]; then
  echo "Resolving AWS account ID..."
  AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
fi

REGISTRY="${AWS_ACCOUNT_ID:-<account_id>}.dkr.ecr.$AWS_REGION.amazonaws.com"
IMAGE_URI="$REGISTRY/$ECR_REPO"
GIT_SHA=$(git -C "$ROOT" rev-parse --short HEAD)

echo "=== Building transcription-worker ==="
echo "  Registry:  $REGISTRY"
echo "  Image:     $IMAGE_URI"
echo "  Tags:      $GIT_SHA, latest${EXTRA_TAG:+, $EXTRA_TAG}"
echo "  Note: model download baked into image (~4 GB, takes 10–20 min first time)"
echo ""

run() {
  echo "  + $*"
  [[ "$DRY_RUN" == "false" ]] && "$@"
}

run aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

run docker build \
  --build-arg "HUGGINGFACE_TOKEN=$HF_TOKEN" \
  -t "$IMAGE_URI:$GIT_SHA" \
  -t "$IMAGE_URI:latest" \
  ${EXTRA_TAG:+-t "$IMAGE_URI:$EXTRA_TAG"} \
  -f "$ROOT/transcription-worker/Dockerfile" "$ROOT"

run docker push "$IMAGE_URI:$GIT_SHA"
run docker push "$IMAGE_URI:latest"
[[ -n "$EXTRA_TAG" ]] && run docker push "$IMAGE_URI:$EXTRA_TAG"

echo ""
if [[ "$DRY_RUN" == "true" ]]; then
  echo "DRY RUN complete — no images were built or pushed."
else
  echo "Pushed: $IMAGE_URI:$GIT_SHA"
fi
