from functools import lru_cache
from pathlib import Path
import re

import yaml

from .config import settings


@lru_cache(maxsize=16)
def load_pack(pack_id: str = "aws-event-driven") -> dict:
    path = Path(settings.game_packs_dir) / pack_id / "manifest.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Game Pack not found: {pack_id}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "missions" not in data:
        raise ValueError(f"Invalid Game Pack manifest: {path}")
    return data


def archive_name(pack: dict, mission: dict) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", f"{pack['id']}-{pack['version']}-{mission['id']}-starter") + ".zip"


def public_missions(pack: dict) -> list[dict]:
    result = []
    for mission in pack.get("missions", []):
        item = {k: v for k, v in mission.items() if k not in {"answer", "validator_secret", "expected_value", "hints"}}
        if mission.get("materials"):
            item["materials"] = {
                "title": mission["materials"].get("title", "Materiales del laboratorio"),
                "instructions": mission["materials"].get("instructions", []),
                "filename": archive_name(pack, mission),
            }
        result.append(item)
    return result


def get_mission(pack: dict, mission_id: str) -> dict | None:
    return next((m for m in pack.get("missions", []) if m.get("id") == mission_id), None)
