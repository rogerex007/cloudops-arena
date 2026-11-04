from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "game-packs" / "aws-event-driven" / "manifest.yaml"


def test_manifest_has_unique_missions_and_points():
    pack = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    missions = pack["missions"]
    ids = [mission["id"] for mission in missions]
    assert len(ids) == len(set(ids))
    assert all(int(mission["points"]) > 0 for mission in missions)
    base_points = sum(int(mission["points"]) for mission in missions if mission.get("type") != "bonus")
    bonus_points = sum(int(mission["points"]) for mission in missions if mission.get("type") == "bonus")
    assert base_points == pack["scoring"]["total_points"]
    assert bonus_points == pack["scoring"]["bonus_points"]
    mission_two = next(mission for mission in missions if mission["id"] == "mission-02")
    assert mission_two["workflow_points"] + mission_two["repository_link_points"] == mission_two["points"]
    assert len(mission_two["resources"]) >= 1


def test_github_workflows_reference_existing_missions():
    pack = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    mission_ids = {mission["id"] for mission in pack["missions"]}
    assert set(pack["github_workflows"].values()).issubset(mission_ids)
