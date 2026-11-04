#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT/game-packs/aws-event-driven/terraform"
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
terraform -chdir="$TF_DIR" destroy -auto-approve -var='use_floci=true' -var='endpoint_url=http://localhost:4566' -var='lambda_endpoint_url=http://floci:4566'
