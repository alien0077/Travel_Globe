#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_OBSERVED = PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "observed-routes.global.json.gz"
DEFAULT_AUDIT = PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "observed-route-pruning-audit.json.gz"


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove ADS-B route points for routes marked adsb_prunable.")
    parser.add_argument("--observed", type=Path, default=DEFAULT_OBSERVED)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    observed = read_json(args.observed)
    audit = read_json(args.audit)
    prunable_ids = {row["id"] for row in audit.get("routes", []) if row.get("decision") == "adsb_prunable"}
    output = args.output or args.observed.with_name(args.observed.name.replace(".json.gz", ".pruned.json.gz"))

    stats = prune_points(observed, prunable_ids)
    observed["shapePruning"] = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "audit": str(args.audit),
        "policy": audit.get("policy"),
        "routesPruned": stats["routesPruned"],
        "representativePointsRemoved": stats["representativePointsRemoved"],
        "variantPointsRemoved": stats["variantPointsRemoved"],
        "totalPointsRemoved": stats["totalPointsRemoved"],
        "note": "Routes marked adsb_prunable retain observed metadata but omit representative/variant point arrays.",
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    write_json_gz(output, observed)
    verify = read_json(output)
    if len(verify.get("routes", [])) != len(observed.get("routes", [])):
        raise SystemExit("Verification failed: route count changed after pruning.")
    if args.replace:
        output.replace(args.observed)
        output = args.observed
    print(
        json.dumps(
            {
                "output": str(output),
                "replacedObserved": args.replace,
                "stats": stats,
                "bytes": {"gzip": output.stat().st_size},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def read_json(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_gz(path: Path, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    with gzip.open(path, "wb", compresslevel=9) as handle:
        handle.write(raw)


def prune_points(observed: dict[str, Any], prunable_ids: set[str]) -> dict[str, int]:
    routes_pruned = 0
    representative_points_removed = 0
    variant_points_removed = 0
    for route in observed.get("routes", []):
        route_id = route.get("id") or f"{route.get('originIata')}-{route.get('destinationIata')}"
        if route_id not in prunable_ids:
            continue
        routes_pruned += 1
        route["shapePruned"] = True
        route["shapeReplacement"] = "great_circle_waypoint_corridor_or_pair_fallback"
        representative = route.get("representative")
        if isinstance(representative, dict):
            points = representative.pop("points", [])
            count = len(points) if isinstance(points, list) else 0
            representative_points_removed += count
            representative["pointsPruned"] = True
            representative["pointCountBeforePrune"] = count
        for variant in route.get("variants") or []:
            if not isinstance(variant, dict):
                continue
            points = variant.pop("points", [])
            count = len(points) if isinstance(points, list) else 0
            variant_points_removed += count
            variant["pointsPruned"] = True
            variant["pointCountBeforePrune"] = count
    return {
        "routesPruned": routes_pruned,
        "representativePointsRemoved": representative_points_removed,
        "variantPointsRemoved": variant_points_removed,
        "totalPointsRemoved": representative_points_removed + variant_points_removed,
    }


if __name__ == "__main__":
    raise SystemExit(main())
