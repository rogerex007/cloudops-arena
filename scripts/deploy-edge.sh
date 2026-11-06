#!/bin/sh
# Deploy the integrated Linux/KVM edge without touching storage volumes.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
if docker inspect cloudops-arena-edge-runner-1 >/dev/null 2>&1; then
  docker exec cloudops-arena-edge-runner-1 python3 -c '
import json,urllib.request
state=json.load(urllib.request.urlopen("http://127.0.0.1:9000/health",timeout=3))
if state["running"]:
    raise SystemExit("Hay evaluaciones activas. Espera a que terminen antes de desplegar.")
'
fi
docker build --target guest -t cloudops-arena-judge-guest:base -f apps/runner/Dockerfile .
docker compose --env-file infra/edge/.env \
  -f infra/edge/compose.yaml \
  -f infra/edge/compose.evaluator.yaml \
  -f infra/edge/compose.playgrounds.yaml \
  up --build -d api web worker runner playgrounds
