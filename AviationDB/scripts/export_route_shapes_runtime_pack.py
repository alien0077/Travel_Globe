#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
DEFAULT_INPUT = ROOT / "shared" / "offline-packs" / "route-shapes" / "global.route-shapes.json.gz"
DEFAULT_SHARED = ROOT / "shared" / "offline-packs" / "route-shapes" / "global.route-shapes.runtime.json"
DEFAULT_PUBLIC = ROOT / "replay-engine" / "public" / "offline-packs" / "route-shapes" / "global.route-shapes.runtime.json"
DEFAULT_SELECTION_DIR = ROOT / "shared" / "offline-packs" / "route-shapes"
RUNTIME_METHODS = {
    "directed_airway_graph",
    "observed_adsb_mapped",
    "recovered_endpoint",
    "approximate_direct_fallback",
    "reverse_route_fallback",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Export compact runtime JSON for Replay Engine route-shapes lookup.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--selection-dir", type=Path, default=DEFAULT_SELECTION_DIR)
    parser.add_argument("--shared-output", type=Path, default=DEFAULT_SHARED)
    parser.add_argument("--public-output", type=Path, default=DEFAULT_PUBLIC)
    args = parser.parse_args()

    pack = read_json_gz(args.input)
    routes = {}
    skipped = 0
    for route in pack.get("routeShapes", []):
        if not add_runtime_route(routes, route.get("id"), route):
            skipped += 1

    selection_added = merge_shape_selections(routes, args.selection_dir)

    payload = {
        "meta": {
            "schemaVersion": 2,
            "generatedAt": pack.get("generatedAt"),
            "sourcePack": args.input.name,
            "summary": {
                **(pack.get("summary") or {}),
                "runtimeSkippedNonDirected": skipped,
                "runtimeSelectionOverrides": selection_added,
            },
        },
        "routes": routes,
    }
    for output in [args.shared_output, args.public_output]:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        update_manifest(output)
    print(
        json.dumps(
            {
                "routes": len(routes),
                "selectionOverrides": selection_added,
                "sharedOutput": str(args.shared_output),
                "sharedBytes": args.shared_output.stat().st_size,
                "publicOutput": str(args.public_output),
                "publicBytes": args.public_output.stat().st_size,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def merge_shape_selections(routes: dict[str, Any], selection_dir: Path) -> int:
    if not selection_dir.exists():
        return 0
    added = 0
    for path in sorted(selection_dir.glob("*.shape-selection.json")):
        selection = json.loads(path.read_text(encoding="utf-8"))
        if selection.get("routeUnavailable"):
            continue
        route_id = selection.get("route") or path.name.removesuffix(".shape-selection.json")
        selected = selection.get("selected")
        if not isinstance(selected, dict):
            continue
        if add_runtime_route(routes, route_id, selected):
            added += 1
    return added


def add_runtime_route(routes: dict[str, Any], route_id: Any, route: dict[str, Any]) -> bool:
    method = route.get("method")
    if not route_id or method not in RUNTIME_METHODS:
        return False
    points = [point for point in route.get("points", []) if isinstance(point, dict)]
    if len(points) < 2:
        return False
    metrics = route.get("metrics") if isinstance(route.get("metrics"), dict) else {}
    distance_km = metrics.get("distanceKm")
    if distance_km is None and metrics.get("distanceNm") is not None:
        distance_km = safe_number(metrics.get("distanceNm")) * 1.852
    routes[str(route_id)] = {
        "m": method,
        "s": safe_number(route.get("score"), precision=2),
        "d": round(safe_number(distance_km) * 1000),
        "w": route_warnings(route),
        "p": [
            [point.get("ident"), point.get("lat"), point.get("lon"), point.get("pointType")]
            for point in points
        ],
    }
    return True


def route_warnings(route: dict[str, Any]) -> list[str]:
    provenance = route.get("provenance") if isinstance(route.get("provenance"), dict) else {}
    warnings = []
    if provenance.get("warning"):
        warnings.append(str(provenance["warning"]))
    if route.get("method") == "approximate_direct_fallback":
        warnings.append("Approximate direct route; not a verified IFR airway.")
    if route.get("method") == "directed_airway_graph":
        warnings.append("IFR airway estimate from the local airgraph; not an observed ADS-B flight track.")
    if route.get("method") == "recovered_endpoint":
        warnings.append("Observed ADS-B track with recovered endpoint; review flag retained.")
    return warnings


def read_json_gz(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def safe_number(value: Any, precision: int | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(number):
        return 0
    return round(number, precision) if precision is not None else number


def update_manifest(runtime_path: Path) -> None:
    manifest_path = runtime_path.with_name("manifest.json")
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtimePack"] = runtime_path.name
    manifest.setdefault("bytes", {})["runtimeJson"] = runtime_path.stat().st_size
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
