#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT/infra/aws-control-plane"
API_URL="$(terraform -chdir="$TF_DIR" output -raw api_base_url)"
WEB_BUCKET="$(terraform -chdir="$TF_DIR" output -raw web_bucket)"
DIST_ID="$(terraform -chdir="$TF_DIR" output -raw cloudfront_distribution_id)"

cd "$ROOT/apps/web"
VITE_API_BASE_URL="$API_URL" npm install
VITE_API_BASE_URL="$API_URL" npm run build
aws s3 sync dist "s3://$WEB_BUCKET" --delete
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths '/*' >/dev/null
printf 'Web deployed: %s\nAPI: %s\n' "$(terraform -chdir="$TF_DIR" output -raw web_url)" "$API_URL"
