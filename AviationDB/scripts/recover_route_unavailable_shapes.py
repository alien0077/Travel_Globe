#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from select_global_route_shapes import (  # noqa: E402
    DEFAULT_AIRGRAPH,
    DEFAULT_AIRPORT_INDEX,
    DEFAULT_PUBLIC_DIR,
    DEFAULT_RELEASE_DIR,
    DEFAULT_ROUTE_FALLBACK,
    DEFAULT_SHARED_DIR,
    pair_source_from_route,
    select_shape_for_route,
    skip_payload,
    write_outputs,
)
from select_pair_route_shape import airport_lookup  # noqa: E402


DEFAULT_INPUT = DEFAULT_RELEASE_DIR / "global.route-shapes.json.gz"
DEFAULT_DIAGNOSTICS = DEFAULT_RELEASE_DIR / "route-unavailable-diagnostics.json"
DEFAULT_MAX_EXISTING_DETOUR = 1.85


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover routeUnavailable rows using the current directed selector.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--airgraph", type=Path, default=DEFAULT_AIRGRAPH)
    parser.add_argument("--route-fallback", type=Path, default=DEFAULT_ROUTE_FALLBACK)
    parser.add_argument("--diagnostics", type=Path, default=DEFAULT_DIAGNOSTICS)
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    parser.add_argument("--shared-dir", type=Path, default=DEFAULT_SHARED_DIR)
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    parser.add_argument("--max-existing-detour", type=float, default=DEFAULT_MAX_EXISTING_DETOUR)
    args = parser.parse_args()

    pack = read_json(args.input)
    airports = airport_lookup(args.airport_index)
    airgraph_pack = json.loads(args.airgraph.read_text(encoding="utf-8"))
    fallback_by_id = {route.get("id"): route for route in read_json(args.route_fallback).get("routes", []) if route.get("id")}
    recoverable_ids = recoverable_route_ids(args.diagnostics)

    existing_shapes = []
    pruned = []
    for route_shape in pack.get("routeShapes") or []:
        detour = ((route_shape.get("metrics") or {}).get("detourRatio"))
        if detour is not None and detour > args.max_existing_detour:
            pruned.append(pruned_payload(route_shape, args.max_existing_detour))
        else:
            existing_shapes.append(route_shape)
    remaining_skipped = []
    recovered = []
    for skipped in pack.get("skipped") or []:
        route_id = skipped.get("id")
        if route_id not in recoverable_ids:
            remaining_skipped.append(skipped)
            continue
        route = fallback_by_id.get(route_id)
        if not route:
            remaining_skipped.append(skipped)
            continue
        origin = airports.get(route.get("originIata"))
        destination = airports.get(route.get("destinationIata"))
        if not origin or not destination:
            remaining_skipped.append(skip_payload(route, origin, destination, "missing_airport"))
            continue
        selected = select_shape_for_route(airgraph_pack, origin, destination, route, pair_source_from_route(route))
        if selected.get("routeUnavailable"):
            remaining_skipped.append(skip_payload(route, origin, destination, selected.get("unavailableReason"), selected))
        else:
            recovered.append(selected)

    route_shapes = existing_shapes + recovered
    remaining_skipped.extend(pruned)
    methods = Counter(route.get("method") for route in route_shapes if route.get("method"))
    if remaining_skipped:
        methods["route_unavailable"] = len(remaining_skipped)
    output = {
        "schemaVersion": pack.get("schemaVersion", 1),
        "generatedAt": datetime.now(UTC).isoformat(),
        "summary": {
            "routesConsidered": len(route_shapes) + len(remaining_skipped),
            "routeShapes": len(route_shapes),
            "skipped": len(remaining_skipped),
            "methods": dict(methods),
            "recoveredFromUnavailable": len(recovered),
            "prunedExcessiveDetour": len(pruned),
            "maxExistingDetour": args.max_existing_detour,
        },
        "routeShapes": route_shapes,
        "skipped": remaining_skipped,
    }
    write_outputs(output, args.release_dir, args.shared_dir, args.public_dir)
    print(
        json.dumps(
            {
                "recovered": len(recovered),
                "prunedExcessiveDetour": len(pruned),
                "remainingSkipped": len(remaining_skipped),
                "summary": output["summary"],
                "recoveredIds": [route["id"] for route in recovered],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def recoverable_route_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    diagnostics = read_json(path)
    return {
        row["id"]
        for row in diagnostics.get("diagnostics", [])
        if row.get("id") and row.get("category") == "selector_constraints_rejected_recoverable"
    }


def pruned_payload(route_shape: dict[str, Any], max_detour: float) -> dict[str, Any]:
    metrics = route_shape.get("metrics") if isinstance(route_shape.get("metrics"), dict) else {}
    return {
        "id": route_shape.get("id"),
        "originIata": route_shape.get("originIata"),
        "destinationIata": route_shape.get("destinationIata"),
        "reason": "detour_ratio_exceeds_limit",
        "detourRatio": metrics.get("detourRatio"),
        "maxAllowedDetourRatio": max_detour,
        "previousMethod": route_shape.get("method"),
        "recommendedResolution": "reselect with stricter directed route validation, observed ADS-B mapping, or keep routeUnavailable",
    }


def read_json(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
