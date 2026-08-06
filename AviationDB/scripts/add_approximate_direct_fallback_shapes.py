#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
DEFAULT_AIRPORT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "airports-index.json"
DEFAULT_ROUTE_FALLBACK = ROOT / "shared" / "offline-packs" / "route-fallback" / "global.route-fallback.json.gz"
DEFAULT_RELEASE_DIR = PROJECT / "data" / "releases" / "private" / "route-shapes"
DEFAULT_INPUT = DEFAULT_RELEASE_DIR / "global.route-shapes.json.gz"
DEFAULT_SHARED_DIR = ROOT / "shared" / "offline-packs" / "route-shapes"
DEFAULT_PUBLIC_DIR = ROOT / "replay-engine" / "public" / "offline-packs" / "route-shapes"


def main() -> int:
    parser = argparse.ArgumentParser(description="Add explicit approximate direct fallback shapes for short static routes.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--route-fallback", type=Path, default=DEFAULT_ROUTE_FALLBACK)
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    parser.add_argument("--shared-dir", type=Path, default=DEFAULT_SHARED_DIR)
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    parser.add_argument("--min-km", type=float, default=20.0)
    parser.add_argument("--max-km", type=float, default=300.0)
    args = parser.parse_args()

    pack = read_json(args.input)
    airports = airport_lookup(args.airport_index)
    fallback_by_id = {row.get("id"): row for row in read_json(args.route_fallback).get("routes", []) if row.get("id")}

    route_shapes = list(pack.get("routeShapes") or [])
    remaining_skipped = []
    added = []
    for skipped in pack.get("skipped") or []:
        route_id = skipped.get("id")
        route = fallback_by_id.get(route_id)
        origin_iata = (route or skipped).get("originIata")
        destination_iata = (route or skipped).get("destinationIata")
        origin = airports.get(origin_iata)
        destination = airports.get(destination_iata)
        distance_km = distance_between(origin, destination)
        if should_add_approximate(route, skipped, distance_km, args.min_km, args.max_km):
            shape = approximate_shape(route, origin, destination, distance_km, skipped)
            route_shapes.append(shape)
            added.append(shape)
        else:
            remaining_skipped.append(skipped)

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
            **summary_carry(pack.get("summary") or {}),
            "approximateDirectFallback": len(added),
            "approximateDirectFallbackPolicy": {
                "bestSource": "static_route_graph",
                "minKm": args.min_km,
                "maxKm": args.max_km,
                "excludedSources": ["airport_connectivity_fallback"],
            },
        },
        "routeShapes": route_shapes,
        "skipped": remaining_skipped,
    }
    write_outputs(output, args.release_dir, args.shared_dir, args.public_dir)
    print(
        json.dumps(
            {
                "added": len(added),
                "remainingSkipped": len(remaining_skipped),
                "summary": output["summary"],
                "examples": [route["id"] for route in added[:40]],
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


def airport_lookup(path: Path) -> dict[str, dict[str, Any]]:
    return {
        row["iataCode"]: row
        for row in json.loads(path.read_text(encoding="utf-8")).get("airports", [])
        if row.get("iataCode")
    }


def should_add_approximate(
    route: dict[str, Any] | None,
    skipped: dict[str, Any],
    distance_km: float | None,
    min_km: float,
    max_km: float,
) -> bool:
    if not route or distance_km is None:
        return False
    if route.get("bestSource") != "static_route_graph":
        return False
    if route.get("hasObservedAdsb"):
        return False
    if not min_km <= distance_km <= max_km:
        return False
    return skipped.get("reason") in {"directed_airway_path_not_found", "detour_ratio_exceeds_limit"}


def approximate_shape(
    route: dict[str, Any],
    origin: dict[str, Any],
    destination: dict[str, Any],
    distance_km: float,
    skipped: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": route["id"],
        "originIata": route["originIata"],
        "destinationIata": route["destinationIata"],
        "method": "approximate_direct_fallback",
        "score": 0,
        "provenance": {
            "source": "static-route-graph-approximate-direct",
            "fallbackRouteBestSource": route.get("bestSource"),
            "fallbackRouteScore": route.get("routeScore"),
            "previousUnavailableReason": skipped.get("reason"),
            "warning": "Approximate route geometry only; not a verified IFR airway route.",
        },
        "metrics": {
            "distanceKm": round(distance_km, 1),
            "distanceNm": round(distance_km / 1.852, 2),
            "directNm": round(distance_km / 1.852, 2),
            "detourRatio": 1.0,
        },
        "points": [
            airport_point(origin),
            *great_circle_points(origin, destination, steps=4),
            airport_point(destination),
        ],
    }


def airport_point(airport: dict[str, Any]) -> dict[str, Any]:
    return {
        "ident": airport.get("iataCode") or airport.get("icaoCode") or airport.get("ident"),
        "lat": airport["latitude"],
        "lon": airport["longitude"],
        "pointType": "AIRPORT",
    }


def great_circle_points(origin: dict[str, Any], destination: dict[str, Any], *, steps: int) -> list[dict[str, Any]]:
    return [
        {
            "ident": f"APPROX{index:02d}",
            "lat": round(point["lat"], 6),
            "lon": round(point["lon"], 6),
            "pointType": "APPROXIMATE",
        }
        for index, point in enumerate(interpolate_great_circle(origin, destination, steps=steps), start=1)
    ]


def interpolate_great_circle(origin: dict[str, Any], destination: dict[str, Any], steps: int) -> list[dict[str, float]]:
    lat1 = math.radians(origin["latitude"])
    lon1 = math.radians(origin["longitude"])
    lat2 = math.radians(destination["latitude"])
    lon2 = math.radians(destination["longitude"])
    delta = 2 * math.asin(
        math.sqrt(math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    )
    points = []
    for index in range(1, steps + 1):
        fraction = index / (steps + 1)
        if delta == 0:
            lat = lat1
            lon = lon1
        else:
            a = math.sin((1 - fraction) * delta) / math.sin(delta)
            b = math.sin(fraction * delta) / math.sin(delta)
            x = a * math.cos(lat1) * math.cos(lon1) + b * math.cos(lat2) * math.cos(lon2)
            y = a * math.cos(lat1) * math.sin(lon1) + b * math.cos(lat2) * math.sin(lon2)
            z = a * math.sin(lat1) + b * math.sin(lat2)
            lat = math.atan2(z, math.sqrt(x * x + y * y))
            lon = math.atan2(y, x)
        points.append({"lat": math.degrees(lat), "lon": math.degrees(lon)})
    return points


def distance_between(origin: dict[str, Any] | None, destination: dict[str, Any] | None) -> float | None:
    if not origin or not destination:
        return None
    rlat1 = math.radians(origin["latitude"])
    rlon1 = math.radians(origin["longitude"])
    rlat2 = math.radians(destination["latitude"])
    rlon2 = math.radians(destination["longitude"])
    value = math.sin((rlat2 - rlat1) / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin((rlon2 - rlon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(value)))


def summary_carry(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in summary.items()
        if key in {"recoveredFromUnavailable", "prunedExcessiveDetour", "maxExistingDetour"}
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


if __name__ == "__main__":
    raise SystemExit(main())
