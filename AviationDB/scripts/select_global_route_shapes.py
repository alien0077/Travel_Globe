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
sys.path.insert(0, str(PROJECT / "scripts"))

from select_pair_route_shape import (  # noqa: E402
    airport_lookup,
    build_great_circle_candidate,
    build_great_circle_waypoint_candidate,
    no_adsb_support,
    score_candidate,
)


DEFAULT_AIRPORT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "airports-index.json"
DEFAULT_AIRGRAPH = ROOT / "shared" / "offline-packs" / "aviation" / "regions" / "global.airgraph.json"
DEFAULT_ROUTE_FALLBACK = ROOT / "shared" / "offline-packs" / "route-fallback" / "global.route-fallback.json.gz"
DEFAULT_RELEASE_DIR = PROJECT / "data" / "releases" / "private" / "route-shapes"
DEFAULT_SHARED_DIR = ROOT / "shared" / "offline-packs" / "route-shapes"
DEFAULT_PUBLIC_DIR = ROOT / "replay-engine" / "public" / "offline-packs" / "route-shapes"
DEFAULT_STATUS = Path("/private/tmp/travel-globe-global-route-shapes/status.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Select great-circle-corridor waypoint shapes for fallback routes.")
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--airgraph", type=Path, default=DEFAULT_AIRGRAPH)
    parser.add_argument("--route-fallback", type=Path, default=DEFAULT_ROUTE_FALLBACK)
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    parser.add_argument("--shared-dir", type=Path, default=DEFAULT_SHARED_DIR)
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--progress-every", type=int, default=250)
    args = parser.parse_args()

    airports = airport_lookup(args.airport_index)
    airgraph_pack = json.loads(args.airgraph.read_text(encoding="utf-8"))
    fallback_pack = read_json(args.route_fallback)
    route_rows = [route for route in fallback_pack.get("routes", []) if route.get("requiresFallbackShape")]
    if args.limit is not None:
        route_rows = route_rows[: args.limit]

    args.status.parent.mkdir(parents=True, exist_ok=True)
    write_status(args.status, "running", total=len(route_rows), processed=0)

    selected_shapes: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    skipped: list[dict[str, Any]] = []
    for index, route in enumerate(route_rows, 1):
        origin = airports.get(route.get("originIata"))
        destination = airports.get(route.get("destinationIata"))
        if not origin or not destination:
            counters["skipped_missing_airport"] += 1
            skipped.append({"id": route.get("id"), "reason": "missing_airport"})
            continue
        pair_source = pair_source_from_route(route)
        selected = select_shape_for_route(airgraph_pack, origin, destination, route, pair_source)
        selected_shapes.append(selected)
        counters[selected["method"]] += 1
        if index % args.progress_every == 0:
            write_status(args.status, "running", total=len(route_rows), processed=index, counters=dict(counters))

    pack = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "summary": {
            "routesConsidered": len(route_rows),
            "routeShapes": len(selected_shapes),
            "skipped": len(skipped),
            "methods": dict(counters),
        },
        "routeShapes": selected_shapes,
        "skipped": skipped[:200],
    }
    write_outputs(pack, args.release_dir, args.shared_dir, args.public_dir)
    write_status(args.status, "complete", total=len(route_rows), processed=len(route_rows), counters=dict(counters))
    print(json.dumps({"summary": pack["summary"], "releaseDir": str(args.release_dir)}, ensure_ascii=False, indent=2))
    return 0


def read_json(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def pair_source_from_route(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "exists": True,
        "source": route.get("bestSource"),
        "count": route.get("openFlightsCount") or 0,
        "aircraftTypes": route.get("aircraftTypes") or [],
        "sourceTypes": route.get("sourceTypes") or [],
    }


def select_shape_for_route(
    airgraph_pack: dict[str, Any],
    origin: dict[str, Any],
    destination: dict[str, Any],
    route: dict[str, Any],
    pair_source: dict[str, Any],
) -> dict[str, Any]:
    adsb_support = no_adsb_support()
    candidates = [
        candidate
        for candidate in [
            build_great_circle_waypoint_candidate(airgraph_pack, origin, destination),
            build_great_circle_candidate(origin, destination),
        ]
        if candidate
    ]
    for candidate in candidates:
        score_candidate(candidate, origin, destination, pair_source, adsb_support)
    candidates.sort(key=lambda item: item["score"], reverse=True)
    selected = candidates[0]
    return {
        "id": route["id"],
        "originIata": route["originIata"],
        "destinationIata": route["destinationIata"],
        "method": selected["method"],
        "score": selected["score"],
        "provenance": {
            **selected["provenance"],
            "fallbackRouteBestSource": route.get("bestSource"),
            "fallbackRouteScore": route.get("routeScore"),
        },
        "metrics": selected["metrics"],
        "points": selected["points"],
    }


def write_outputs(pack: dict[str, Any], release_dir: Path, shared_dir: Path, public_dir: Path) -> None:
    raw = json.dumps(pack, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    gz = gzip.compress(raw, compresslevel=9)
    manifest = {
        "schemaVersion": 1,
        "generatedAt": pack["generatedAt"],
        "pack": "global.route-shapes.json.gz",
        "summary": pack["summary"],
        "bytes": {"json": len(raw), "gzip": len(gz)},
    }
    manifest_raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    for directory in [release_dir, shared_dir, public_dir]:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "global.route-shapes.json.gz").write_bytes(gz)
        (directory / "manifest.json").write_bytes(manifest_raw)


def write_status(path: Path, state: str, **extra: Any) -> None:
    payload = {"state": state, "updatedAt": datetime.now(UTC).isoformat(), **extra}
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
