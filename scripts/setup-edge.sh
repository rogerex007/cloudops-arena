#!/bin/sh
# Generate local preview credentials without displaying them or replacing a file.
set -eu
umask 077
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file="$project_dir/infra/edge/.env"
if [ -e "$env_file" ]; then
  printf '%s\n' 'infra/edge/.env already exists; credentials were not changed.'
else
command -v openssl >/dev/null 2>&1 || {
  printf '%s\n' 'OpenSSL is required to generate credentials.' >&2
  exit 1
}
jwt_secret=$(openssl rand -hex 32)
admin_password=$(openssl rand -hex 24)
webhook_secret=$(openssl rand -hex 32)
(
  set -C
  {
    printf 'ADMIN_USERNAME=instructor\nADMIN_PASSWORD=%s\n' "$admin_password"
    printf 'JWT_SECRET=%s\nGITHUB_WEBHOOK_SECRET=%s\n' "$jwt_secret" "$webhook_secret"
    printf 'FLOCI_IMAGE=floci/floci:latest\nCLOUDFLARED_IMAGE=cloudflare/cloudflared:latest\n'
  } > "$env_file"
)
mkdir -p "$project_dir/infra/edge/.secrets"
printf '%s\n' 'Created infra/edge/.env. Read credentials locally; keep this file private.'
fi
secret_dir="$project_dir/infra/edge/.secrets"
mkdir -p "$secret_dir"
chmod 700 "$secret_dir"
if [ ! -e "$secret_dir/runner-token" ]; then
  openssl rand -hex 32 > "$secret_dir/runner-token"
fi
chmod 644 "$secret_dir/runner-token"
if [ ! -e "$secret_dir/github-app.json" ]; then
  printf '{}\n' > "$secret_dir/github-app.json"
fi
if [ ! -e "$secret_dir/github-app.pem" ]; then
  touch "$secret_dir/github-app.pem"
fi
printf '%s\n' 'Next steps: docs/cloudflare-preview.md. No tunnel has been started.'
