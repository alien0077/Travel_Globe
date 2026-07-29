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
DEFAULT_AIRGRAPH = ROOT / "shared" / "offline-packs" / "aviation" / "regions" / "global.airgraph.json"
DEFAULT_OBSERVED = PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "observed-routes.global.json.gz"
DEFAULT_OUTPUT = PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "observed-route-pruning-audit.json.gz"
DEFAULT_STATUS = Path("/private/tmp/travel-globe-observed-pruning/status.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit which observed ADS-B route shapes can be pruned.")
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--airgraph", type=Path, default=DEFAULT_AIRGRAPH)
    parser.add_argument("--observed", type=Path, default=DEFAULT_OBSERVED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--progress-every", type=int, default=1000)
    parser.add_argument("--mean-threshold-km", type=float, default=85)
    parser.add_argument("--max-threshold-km", type=float, default=260)
    parser.add_argument("--distance-ratio-threshold", type=float, default=0.28)
    args = parser.parse_args()

    airports = {
        row["iataCode"]: row
        for row in json.loads(args.airport_index.read_text(encoding="utf-8")).get("airports", [])
        if row.get("iataCode")
    }
    airgraph = json.loads(args.airgraph.read_text(encoding="utf-8"))
    waypoint_index = build_waypoint_index(airgraph["points"])
    observed = read_json(args.observed)
    routes = observed.get("routes", [])
    if args.limit is not None:
        routes = routes[: args.limit]

    args.status.parent.mkdir(parents=True, exist_ok=True)
    write_status(args.status, "running", total=len(routes), processed=0)
    rows: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    for index, route in enumerate(routes, 1):
        row = audit_route(
            route,
            airports,
            waypoint_index,
            mean_threshold_km=args.mean_threshold_km,
            max_threshold_km=args.max_threshold_km,
            distance_ratio_threshold=args.distance_ratio_threshold,
        )
        rows.append(row)
        counters[row["decision"]] += 1
        if index % args.progress_every == 0:
            write_status(args.status, "running", total=len(routes), processed=index, counters=dict(counters))

    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "policy": {
            "meanThresholdKm": args.mean_threshold_km,
            "maxThresholdKm": args.max_threshold_km,
            "distanceRatioThreshold": args.distance_ratio_threshold,
        },
        "summary": {
            "routesAudited": len(rows),
            "decisions": dict(counters),
            "adsbPrunable": counters["adsb_prunable"],
            "adsbKeep": counters["adsb_keep"],
            "skipped": sum(value for key, value in counters.items() if key.startswith("skip_")),
        },
        "routes": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(report, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    with gzip.open(args.output, "wb", compresslevel=9) as handle:
        handle.write(raw)
    write_status(args.status, "complete", total=len(routes), processed=len(routes), counters=dict(counters), output=str(args.output))
    print(json.dumps({"output": str(args.output), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0


def read_json(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def build_waypoint_index(points: list[list[Any]]) -> dict[tuple[int, int], list[dict[str, Any]]]:
    index: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in points:
        point = {"ident": row[0], "lat": float(row[1]), "lon": float(row[2]), "pointType": row[3]}
        key = (math.floor(point["lat"] / 5), math.floor(point["lon"] / 5))
        index.setdefault(key, []).append(point)
    return index


def audit_route(
    route: dict[str, Any],
    airports: dict[str, dict[str, Any]],
    waypoint_index: dict[tuple[int, int], list[dict[str, Any]]],
    mean_threshold_km: float,
    max_threshold_km: float,
    distance_ratio_threshold: float,
) -> dict[str, Any]:
    route_id = route.get("id") or f"{route.get('originIata')}-{route.get('destinationIata')}"
    origin = airports.get(route.get("originIata"))
    destination = airports.get(route.get("destinationIata"))
    representative = (route.get("representative") or {}).get("points") or []
    if not origin or not destination:
        return skipped(route_id, route, "skip_missing_airport")
    if len(representative) < 2:
        return skipped(route_id, route, "skip_missing_representative")
    synthetic = build_gc_waypoint_route(origin, destination, waypoint_index)
    observed_points = [{"lat": float(lat), "lon": float(lon)} for lat, lon in representative]
    synthetic_points = [{"lat": point["lat"], "lon": point["lon"]} for point in synthetic]
    observed_distance = route_distance_km(observed_points)
    synthetic_distance = route_distance_km(synthetic_points)
    metrics = compare_shapes(observed_points, synthetic_points)
    distance_ratio_delta = abs(observed_distance - synthetic_distance) / max(1, synthetic_distance)
    is_prunable = (
        metrics["meanObservedToSyntheticKm"] <= mean_threshold_km
        and metrics["maxObservedToSyntheticKm"] <= max_threshold_km
        and distance_ratio_delta <= distance_ratio_threshold
    )
    return {
        "id": route_id,
        "originIata": route.get("originIata"),
        "destinationIata": route.get("destinationIata"),
        "decision": "adsb_prunable" if is_prunable else "adsb_keep",
        "sampleCount": route.get("sampleCount") or 0,
        "variantCount": route.get("variantCount") or 0,
        "metrics": {
            **metrics,
            "observedDistanceKm": round(observed_distance, 1),
            "syntheticDistanceKm": round(synthetic_distance, 1),
            "distanceRatioDelta": round(distance_ratio_delta, 3),
            "syntheticMethod": "great_circle_waypoint_corridor",
            "syntheticWaypointCount": max(0, len(synthetic) - 2),
        },
    }


def skipped(route_id: str, route: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "id": route_id,
        "originIata": route.get("originIata"),
        "destinationIata": route.get("destinationIata"),
        "decision": reason,
        "sampleCount": route.get("sampleCount") or 0,
        "variantCount": route.get("variantCount") or 0,
    }


def build_gc_waypoint_route(
    origin: dict[str, Any],
    destination: dict[str, Any],
    waypoint_index: dict[tuple[int, int], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    last_t = 0.0
    for target_t in [index / 10 for index in range(1, 10)]:
        best: dict[str, Any] | None = None
        for point in candidate_waypoints(origin, destination, waypoint_index):
            projection = project_distance_km(point["lat"], point["lon"], origin, destination)
            t = projection["t"]
            if not 0.04 <= t <= 0.96 or projection["distanceKm"] > 180:
                continue
            if selected and t <= last_t + 0.035:
                continue
            rank = projection["distanceKm"] + abs(t - target_t) * 260
            if best is None or rank < best["rank"]:
                best = {**point, "rank": rank, "t": t}
        if best is not None:
            selected.append({key: value for key, value in best.items() if key not in {"rank", "t"}})
            last_t = float(best["t"])
    if len(selected) < 4:
        return [airport_point(origin), *great_circle_points(origin, destination), airport_point(destination)]
    return [airport_point(origin), *selected, airport_point(destination)]


def candidate_waypoints(
    origin: dict[str, Any],
    destination: dict[str, Any],
    waypoint_index: dict[tuple[int, int], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    min_lat = min(origin["latitude"], destination["latitude"]) - 3
    max_lat = max(origin["latitude"], destination["latitude"]) + 3
    min_lon = min(origin["longitude"], destination["longitude"]) - 3
    max_lon = max(origin["longitude"], destination["longitude"]) + 3
    rows: list[dict[str, Any]] = []
    for lat_cell in range(math.floor(min_lat / 5), math.floor(max_lat / 5) + 1):
        for lon_cell in range(math.floor(min_lon / 5), math.floor(max_lon / 5) + 1):
            rows.extend(waypoint_index.get((lat_cell, lon_cell), []))
    return rows


def airport_point(airport: dict[str, Any]) -> dict[str, Any]:
    return {"ident": airport["iataCode"], "lat": airport["latitude"], "lon": airport["longitude"]}


def great_circle_points(origin: dict[str, Any], destination: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"ident": f"GC{index:02d}", "lat": point["lat"], "lon": point["lon"]}
        for index, point in enumerate(interpolate_great_circle(origin, destination, 10), 1)
    ]


def interpolate_great_circle(origin: dict[str, Any], destination: dict[str, Any], steps: int) -> list[dict[str, float]]:
    return [interpolate_linear(origin, destination, index / (steps + 1)) for index in range(1, steps + 1)]


def interpolate_linear(origin: dict[str, Any], destination: dict[str, Any], fraction: float) -> dict[str, float]:
    return {
        "lat": origin["latitude"] + (destination["latitude"] - origin["latitude"]) * fraction,
        "lon": origin["longitude"] + (destination["longitude"] - origin["longitude"]) * fraction,
    }


def compare_shapes(observed: list[dict[str, float]], synthetic: list[dict[str, float]]) -> dict[str, float]:
    distances = [distance_to_polyline_km(point, synthetic) for point in observed]
    reverse = [distance_to_polyline_km(point, observed) for point in synthetic]
    return {
        "meanObservedToSyntheticKm": round(sum(distances) / len(distances), 1),
        "maxObservedToSyntheticKm": round(max(distances), 1),
        "meanSyntheticToObservedKm": round(sum(reverse) / len(reverse), 1),
        "maxSyntheticToObservedKm": round(max(reverse), 1),
    }


def distance_to_polyline_km(point: dict[str, float], line: list[dict[str, float]]) -> float:
    return min(distance_to_segment_km(point, line[index - 1], line[index]) for index in range(1, len(line)))


def distance_to_segment_km(point: dict[str, float], a: dict[str, float], b: dict[str, float]) -> float:
    mid_lat = math.radians((a["lat"] + b["lat"] + point["lat"]) / 3)
    ax, ay = 0.0, 0.0
    bx = (b["lon"] - a["lon"]) * 111.320 * math.cos(mid_lat)
    by = (b["lat"] - a["lat"]) * 110.574
    px = (point["lon"] - a["lon"]) * 111.320 * math.cos(mid_lat)
    py = (point["lat"] - a["lat"]) * 110.574
    denom = bx * bx + by * by
    t = 0.0 if denom == 0 else max(0.0, min(1.0, (px * bx + py * by) / denom))
    return math.hypot(px - (ax + t * bx), py - (ay + t * by))


def project_distance_km(lat: float, lon: float, origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, float]:
    mid_lat = math.radians((origin["latitude"] + destination["latitude"]) / 2)
    bx = (destination["longitude"] - origin["longitude"]) * 111.320 * math.cos(mid_lat)
    by = (destination["latitude"] - origin["latitude"]) * 110.574
    px = (lon - origin["longitude"]) * 111.320 * math.cos(mid_lat)
    py = (lat - origin["latitude"]) * 110.574
    denom = bx * bx + by * by
    t = 0.0 if denom == 0 else (px * bx + py * by) / denom
    return {"t": t, "distanceKm": math.hypot(px - t * bx, py - t * by)}


def route_distance_km(points: list[dict[str, float]]) -> float:
    return sum(haversine_km(points[index - 1]["lat"], points[index - 1]["lon"], points[index]["lat"], points[index]["lon"]) for index in range(1, len(points)))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = rlat2 - rlat1
    dlon = math.radians(lon2 - lon1)
    value = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1, math.sqrt(value)))


def write_status(path: Path, state: str, **extra: Any) -> None:
    path.write_text(json.dumps({"state": state, "updatedAt": datetime.now(UTC).isoformat(), **extra}, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
