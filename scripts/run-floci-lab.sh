#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT/game-packs/aws-event-driven/terraform"
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
terraform -chdir="$TF_DIR" init
terraform -chdir="$TF_DIR" fmt -recursive
terraform -chdir="$TF_DIR" validate
terraform -chdir="$TF_DIR" plan -var='use_floci=true' -var='endpoint_url=http://localhost:4566' -var='lambda_endpoint_url=http://floci:4566'
if [[ "${APPLY:-false}" == "true" ]]; then
  terraform -chdir="$TF_DIR" apply -auto-approve -var='use_floci=true' -var='endpoint_url=http://localhost:4566' -var='lambda_endpoint_url=http://floci:4566'
fi
