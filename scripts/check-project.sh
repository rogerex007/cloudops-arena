#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python -m compileall -q "$ROOT/apps/api" "$ROOT/game-packs/aws-event-driven/functions" "$ROOT/game-packs/aws-event-driven/tests"
python - "$ROOT" <<'PY'
from pathlib import Path
import sys, yaml
root = Path(sys.argv[1])
for path in [root / "infra/local/compose.yaml", root / "game-packs/aws-event-driven/manifest.yaml"]:
    yaml.safe_load(path.read_text(encoding="utf-8"))
for path in (root / ".github/workflows").glob("*.yml"):
    yaml.safe_load(path.read_text(encoding="utf-8"))
print("YAML manifests: OK")
PY
PYTHONPATH="$ROOT/apps/api" python -m pytest -q "$ROOT/apps/api/tests" "$ROOT/game-packs/aws-event-driven/tests"
