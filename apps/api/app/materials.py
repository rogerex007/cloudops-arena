"""Build small, authenticated starter archives from explicit Game Pack file lists."""
import hashlib
import io
import json
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Response

from .config import settings
from .db import get_item
from .gamepack import archive_name, get_mission, load_pack
from .security import require_participant

router = APIRouter()
MAX_FILE_BYTES = 256 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024


def safe_path(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Invalid material path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("Material path must be relative")
    if any(part in {".git", ".secrets", "__pycache__", "tests", "validators"}
           or part == ".env" or part.startswith(".env.") for part in path.parts):
        raise ValueError("Sensitive materials are not downloadable")
    if path.suffix.lower() in {".tfstate", ".tfvars", ".pem", ".key", ".zip"}:
        raise ValueError("Sensitive or generated material")
    return path


def build_archive(pack: dict, mission: dict) -> bytes:
    roots = Path(settings.game_packs_dir).resolve()
    root = (roots / pack["id"]).resolve()
    if not root.is_relative_to(roots) or root == roots:
        raise ValueError("Invalid Game Pack root")
    entries = mission.get("materials", {}).get("files", [])
    if not entries or len(entries) > 100:
        raise ValueError("Invalid material list")
    files = {}
    total = 0
    for entry in entries:
        source = (root / str(safe_path(entry["source"]))).resolve()
        destination = str(safe_path(entry["destination"]))
        if not source.is_relative_to(root) or destination in files or destination == "ARENA-KIT.json":
            raise ValueError("Unsafe or duplicate material")
        with source.open("rb") as stream:
            content = stream.read(MAX_FILE_BYTES + 1)
        total += len(content)
        if len(content) > MAX_FILE_BYTES or total > MAX_ARCHIVE_BYTES:
            raise ValueError("Materials exceed archive limits")
        files[destination] = content
    metadata = {
        "game_pack": pack["id"], "pack_version": str(pack["version"]),
        "mission_id": mission["id"], "materials_revision": mission["materials"].get("revision", 1),
        "files": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())},
    }
    files["ARENA-KIT.json"] = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


@router.get("/api/v1/participant/missions/{mission_id}/materials")
def download_materials(mission_id: str, principal: dict = Depends(require_participant)):
    pk = f"EVENT#{principal['event_id']}"
    participant = get_item(pk, f"USER#{principal['sub']}")
    if not participant or participant.get("team_id") != principal["team_id"]:
        raise HTTPException(403, "Tu registro en este evento ya no está disponible.")
    event = get_item(pk, "META")
    if not event:
        raise HTTPException(404, "No encontramos este evento.")
    completed = get_item(pk, f"SUB#{principal['team_id']}#{mission_id}")
    if event.get("active_mission_id") != mission_id and (not completed or completed.get("status") != "passed"):
        raise HTTPException(403, "El instructor debe activar esta misión para descargar sus materiales.")
    pack = load_pack(event.get("game_pack", "aws-event-driven"))
    mission = get_mission(pack, mission_id)
    if not mission or not mission.get("materials"):
        raise HTTPException(404, "Esta misión no tiene un kit descargable.")
    try:
        payload = build_archive(pack, mission)
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(503, "El kit no está disponible. Consulta con el instructor.") from exc
    return Response(payload, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{archive_name(pack, mission)}"',
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "ETag": '"' + hashlib.sha256(payload).hexdigest() + '"',
    })
