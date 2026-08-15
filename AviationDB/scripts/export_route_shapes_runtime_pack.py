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
DEFAULT_COMPLETION_PACK = DEFAULT_SELECTION_DIR / "global.route-shapes.runtime-completions.json"
DEFAULT_CORRIDOR_PACK = DEFAULT_SELECTION_DIR / "global.route-shapes.runtime-corridor-025.json"
RUNTIME_METHODS = {
    "corridor_025_graph",
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
    parser.add_argument("--completion-pack", type=Path, default=DEFAULT_COMPLETION_PACK)
    parser.add_argument("--corridor-pack", type=Path, default=DEFAULT_CORRIDOR_PACK)
    parser.add_argument("--shared-output", type=Path, default=DEFAULT_SHARED)
    parser.add_argument("--public-output", type=Path, default=DEFAULT_PUBLIC)
    args = parser.parse_args()

    pack = read_json_gz(args.input)
    routes = {}
    skipped = 0
    for route in pack.get("routeShapes", []):
        if not add_runtime_route(routes, route.get("id"), route):
            skipped += 1

    completion_added = merge_completion_pack(routes, args.completion_pack)
    corridor_added = merge_corridor_pack(routes, args.corridor_pack)
    selection_added = merge_shape_selections(routes, args.selection_dir)

    payload = {
        "meta": {
            "schemaVersion": 2,
            "generatedAt": pack.get("generatedAt"),
            "sourcePack": args.input.name,
            "summary": {
                **(pack.get("summary") or {}),
                "runtimeSkippedNonDirected": skipped,
                "runtimeCompletionRoutes": completion_added,
                "runtimeCorridorRoutes": corridor_added,
                "runtimeSelectionOverrides": selection_added,
            },
        },
        "routes": routes,
    }
    for output in [args.shared_output, args.public_output]:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        update_manifest(output, payload["meta"]["summary"])
    print(
        json.dumps(
            {
                "routes": len(routes),
                "completionRoutes": completion_added,
                "corridorRoutes": corridor_added,
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
        if (
            selected.get("method") == "directed_airway_graph"
            and isinstance(routes.get(str(route_id)), dict)
            and routes[str(route_id)].get("m") == "corridor_025_graph"
        ):
            continue
        if add_runtime_route(routes, route_id, selected):
            added += 1
    return added


def merge_completion_pack(routes: dict[str, Any], completion_path: Path) -> int:
    """Merge routes produced by reverse completion as a reproducible source.

    Reverse completion historically mutated the compact runtime JSON directly,
    leaving 1,431 routes that could not be reconstructed by this exporter.
    The completion pack makes that intermediate step explicit and reviewable.
    Selection overlays are applied afterwards so an observed selection remains
    the final source when both files contain the same route.
    """
    if not completion_path.exists():
        return 0
    payload = json.loads(completion_path.read_text(encoding="utf-8"))
    completion_routes = payload.get("routes") if isinstance(payload, dict) else None
    if not isinstance(completion_routes, dict):
        return 0
    added = 0
    for route_id, route in sorted(completion_routes.items()):
        if add_compact_runtime_route(routes, route_id, route):
            added += 1
    return added


def merge_corridor_pack(routes: dict[str, Any], corridor_path: Path) -> int:
    """Apply 0.25-degree corridor shapes before observed selections."""
    if not corridor_path.exists():
        return 0
    payload = json.loads(corridor_path.read_text(encoding="utf-8"))
    corridor_routes = payload.get("routes") if isinstance(payload, dict) else None
    if not isinstance(corridor_routes, dict):
        return 0
    added = 0
    for route_id, route in sorted(corridor_routes.items()):
        if add_compact_runtime_route(routes, route_id, route):
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


def add_compact_runtime_route(routes: dict[str, Any], route_id: Any, route: dict[str, Any]) -> bool:
    """Add a compact route emitted by the reverse-completion step."""
    if not route_id or not isinstance(route, dict) or route.get("m") not in RUNTIME_METHODS:
        return False
    points = route.get("p")
    if not isinstance(points, list) or len(points) < 2:
        return False
    compact_points = []
    for point in points:
        if not isinstance(point, list) or len(point) < 4:
            return False
        compact_points.append([point[0], point[1], point[2], point[3]])
    routes[str(route_id)] = {
        "m": route.get("m"),
        "s": safe_number(route.get("s"), precision=2),
        "d": round(safe_number(route.get("d"))),
        "w": [str(value) for value in route.get("w", []) if value],
        "p": compact_points,
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


def update_manifest(runtime_path: Path, runtime_summary: dict[str, Any] | None = None) -> None:
    manifest_path = runtime_path.with_name("manifest.json")
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtimePack"] = runtime_path.name
    manifest.setdefault("bytes", {})["runtimeJson"] = runtime_path.stat().st_size
    if runtime_summary:
        manifest.setdefault("summary", {}).update(runtime_summary)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
