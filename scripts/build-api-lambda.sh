#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/build"
rm -rf "$ROOT/build/lambda-package" "$ROOT/build/api-lambda.zip"

docker run --rm \
  -v "$ROOT:/src" \
  -w /src \
  python:3.12-slim \
  bash -lc '
    set -euo pipefail
    mkdir -p build/lambda-package
    pip install --no-cache-dir -r apps/api/requirements.txt -t build/lambda-package
    cp apps/api/lambda_handler.py build/lambda-package/
    cp -R apps/api/app build/lambda-package/app
    cp -R game-packs build/lambda-package/game-packs
    cd build/lambda-package
    python -m compileall -q app lambda_handler.py
    python -m zipfile -c ../api-lambda.zip .
  '
echo "Built $ROOT/build/api-lambda.zip"
