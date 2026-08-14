from __future__ import annotations

import importlib.util
from pathlib import Path


def load_module(relative_path: str, name: str):
    path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


merge_shapes = load_module(
    "scripts/merge_accepted_review_route_shapes.py",
    "merge_accepted_review_route_shapes",
)
runtime_export = load_module(
    "scripts/export_route_shapes_runtime_pack.py",
    "export_route_shapes_runtime_pack",
)


def test_accepted_observed_shape_can_replace_static_ifr_graph():
    assert merge_shapes.is_protected_existing_method("directed_airway_graph") is False
    assert merge_shapes.is_protected_existing_method("reverse_route_fallback") is False
    assert merge_shapes.is_protected_existing_method("observed_adsb_mapped") is True
    assert merge_shapes.is_protected_existing_method("recovered_endpoint") is True


def test_runtime_pack_keeps_observed_and_ifr_provenance_distinct():
    routes = {}
    assert runtime_export.add_runtime_route(
        routes,
        "KHH-NRT",
        {
            "method": "directed_airway_graph",
            "score": 10,
            "points": [
                {"ident": "KHH", "lat": 22.5, "lon": 120.3, "pointType": "AIRPORT"},
                {"ident": "NRT", "lat": 35.7, "lon": 140.3, "pointType": "AIRPORT"},
            ],
        },
    )
    assert "not an observed ADS-B flight track" in routes["KHH-NRT"]["w"][0]

    assert runtime_export.add_runtime_route(
        routes,
        "TPE-NRT",
        {
            "method": "recovered_endpoint",
            "score": 10,
            "provenance": {"warning": "review"},
            "points": [
                {"ident": "TPE", "lat": 25.0, "lon": 121.2, "pointType": "AIRPORT"},
                {"ident": "NRT", "lat": 35.7, "lon": 140.3, "pointType": "AIRPORT"},
            ],
        },
    )
    assert routes["TPE-NRT"]["m"] == "recovered_endpoint"
    assert "recovered endpoint" in routes["TPE-NRT"]["w"][-1]
