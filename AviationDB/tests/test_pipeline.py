from pathlib import Path

from aviationdb.build import build_all
from aviationdb.exporters.app_pack import export_app_pack
from aviationdb.repository import AviationRepository
from aviationdb.routing import route_between_airports
from aviationdb.validation import validate_database


def test_fixture_build_validate_route_and_export(tmp_path: Path) -> None:
    repo = AviationRepository(tmp_path / "aviation.sqlite")
    build_all(repo)

    issues = validate_database(repo)
    assert [issue for issue in issues if issue.severity == "error"] == []
    assert repo.scalar("SELECT COUNT(*) FROM nav_point WHERE ident = 'ELATO'") >= 1
    assert repo.scalar("SELECT COUNT(*) FROM airway_segment") >= 1

    route = route_between_airports(repo, "RCTP", "RJAA", region="asia-east")
    assert route.method == "airway_graph"
    assert route.waypoints[:2] == ["TONGA", "MAKOT"]
    assert "KAPLI" in route.waypoints

    fallback = route_between_airports(repo, "KSFO", "RJAA", region="asia-east")
    assert fallback.method == "great_circle_fallback"
    assert fallback.warnings

    manifest = export_app_pack(repo, "asia-east", tmp_path / "pack")
    assert manifest["regions"][0]["points"] >= 4
    assert (tmp_path / "pack" / "regions" / "asia-east.airgraph.json.gz").exists()

    public_na_manifest = export_app_pack(repo, "north-america", tmp_path / "pack-na-public")
    assert public_na_manifest["licenseMode"] == "public"
    assert public_na_manifest["regions"][0]["points"] == 0

    private_na_manifest = export_app_pack(
        repo,
        "north-america",
        tmp_path / "pack-na-private",
        include_private=True,
    )
    assert private_na_manifest["licenseMode"] == "private"
    assert private_na_manifest["regions"][0]["points"] >= 1
    assert private_na_manifest["payloads"]["airgraph"][0]["public"] is False
    repo.close()
