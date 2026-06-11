#!/usr/bin/env bash
# Validate all Terraform environments: fmt check + validate.
# Mirrors .github/workflows/tf-validate.yml for local use.
#
# Usage:
#   ./scripts/ci/validate-tf.sh           # check all environments
#   ./scripts/ci/validate-tf.sh prod      # check a single environment by name

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INFRA_DIR="$ROOT/infra/environments"
FILTER="${1:-}"
FAILED=()

if [[ ! -d "$INFRA_DIR" ]]; then
  echo "ERROR: $INFRA_DIR not found"
  exit 1
fi

for env_dir in "$INFRA_DIR"/*/; do
  env_name="$(basename "$env_dir")"

  if [[ -n "$FILTER" && "$env_name" != "$FILTER" ]]; then
    continue
  fi

  echo "--- $env_name ---"

  if ! terraform -chdir="$env_dir" fmt -check -diff; then
    echo "  FAIL: fmt check"
    FAILED+=("$env_name (fmt)")
  else
    echo "  OK:   fmt"
  fi

  if ! terraform -chdir="$env_dir" init -backend=false -input=false -no-color 2>&1 \
      | grep -v "^$" | sed 's/^/  /'; then
    echo "  FAIL: init"
    FAILED+=("$env_name (init)")
    continue
  fi

  if ! terraform -chdir="$env_dir" validate -no-color 2>&1 | sed 's/^/  /'; then
    echo "  FAIL: validate"
    FAILED+=("$env_name (validate)")
  else
    echo "  OK:   validate"
  fi

  echo ""
done

if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo "FAILED environments:"
  for item in "${FAILED[@]}"; do
    echo "  - $item"
  done
  exit 1
fi

echo "All environments passed."
