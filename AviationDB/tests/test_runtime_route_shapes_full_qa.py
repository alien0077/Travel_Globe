from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path


def load_module(relative_path: str, name: str):
    path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qa = load_module("scripts/validate_runtime_route_shapes_full.py", "validate_runtime_route_shapes_full")
exporter = load_module("scripts/export_route_shapes_runtime_pack.py", "export_route_shapes_runtime_pack_for_full_qa")


def compact_point(ident: str, lat: float, lon: float, point_type: str = "SIGNIFICANT_POINT"):
    return [ident, lat, lon, point_type]


def test_full_qa_reconstructs_base_completion_and_selection_routes(tmp_path):
    base_path = tmp_path / "base.json.gz"
    selection_dir = tmp_path / "selections"
    selection_dir.mkdir()
    completion_path = tmp_path / "completion.json"

    base_route = {
        "id": "AAA-BBB",
        "method": "directed_airway_graph",
        "score": 1,
        "metrics": {"distanceKm": 111.2},
        "points": [
            {"ident": "AAA", "lat": 0, "lon": 0, "pointType": "AIRPORT"},
            {"ident": "BBB", "lat": 1, "lon": 0, "pointType": "AIRPORT"},
        ],
    }
    with gzip.open(base_path, "wt", encoding="utf-8") as handle:
        json.dump({"routeShapes": [base_route]}, handle)

    selection = {
        "route": "CCC-DDD",
        "selected": {
            "method": "observed_adsb_mapped",
            "score": 2,
            "metrics": {"distanceKm": 111.2},
            "provenance": {"validationClassification": "observed_adsb_needs_review"},
            "points": [
                {"ident": "CCC", "lat": 0, "lon": 0, "pointType": "AIRPORT"},
                {"ident": "DDD", "lat": 1, "lon": 0, "pointType": "AIRPORT"},
            ],
        },
    }
    (selection_dir / "CCC-DDD.shape-selection.json").write_text(json.dumps(selection), encoding="utf-8")
    completion = {
        "routes": {
            "EEE-FFF": {
                "m": "reverse_route_fallback",
                "s": 3,
                "d": 111200,
                "w": ["fallback"],
                "p": [compact_point("EEE", 0, 0, "AIRPORT"), compact_point("FFF", 1, 0, "AIRPORT")],
            }
        }
    }
    completion_path.write_text(json.dumps(completion), encoding="utf-8")

    base = qa.read_json_gz(base_path)
    expected, sources, selection_meta = qa.reconstruct_expected(base, selection_dir, completion_path, tmp_path / "missing-corridor.json", exporter)
    assert set(expected) == {"AAA-BBB", "CCC-DDD", "EEE-FFF"}
    assert sources["EEE-FFF"] == "completion_pack"
    assert sources["CCC-DDD"] == "selection_override"
    assert selection_meta["CCC-DDD"]["method"] == "observed_adsb_mapped"

    parity = qa.compare_runtime(expected, expected, sources)
    assert parity["missing"] == []
    assert parity["extra"] == []
    assert parity["mismatches"] == []

    inspected = qa.inspect_route("AAA-BBB", expected["AAA-BBB"], {})
    assert inspected["geometryQaPassed"] is True
    assert inspected["endpointAliases"] == []


def test_full_qa_flags_ifr_route_without_explicit_warning():
    route = {
        "m": "directed_airway_graph",
        "d": 111200,
        "p": [compact_point("AAA", 0, 0, "AIRPORT"), compact_point("BBB", 1, 0, "AIRPORT")],
        "w": [],
    }
    assert qa.evidence_class(route, None) == "ifr_estimate_missing_warning"


def test_full_qa_catches_distance_metadata_error():
    route = {
        "m": "observed_adsb_mapped",
        "d": 1000,
        "p": [compact_point("AAA", 0, 0, "AIRPORT"), compact_point("BBB", 1, 0, "AIRPORT")],
        "w": ["review"],
    }
    report = qa.inspect_route("AAA-BBB", route, {})
    assert report["geometryQaPassed"] is False
    assert "geometry_distance_mismatch" in report["errors"]
