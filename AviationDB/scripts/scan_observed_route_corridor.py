#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from aviationdb.observed_routes import (  # noqa: E402
    Airport,
    AirportIndex,
    BuildOptions,
    TracePoint,
    fetch_preferred_releases,
    haversine_km,
    iter_trace_payloads_from_split_tar,
    parse_trace_points,
    route_distance_km,
    split_legs,
)
from build_observed_routes_range import _download_with_curl  # noqa: E402


DEFAULT_AIRPORT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "airports-index.json"
DEFAULT_WORK_DIR = Path("/private/tmp/travel-globe-adsblol-diagnostics")
DEFAULT_OUTPUT_DIR = PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "diagnostics"


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan ADSB.lol traces for legs matching route corridors.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--routes", nargs="+", required=True, help="Route pairs like KHH-NRT DMK-KHH.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--corridor-km", type=float, default=280)
    parser.add_argument("--endpoint-km", type=float, default=900)
    parser.add_argument("--min-corridor-fraction", type=float, default=0.35)
    parser.add_argument("--min-progress", type=float, default=0.35)
    parser.add_argument("--top", type=int, default=200)
    parser.add_argument("--min-points", type=int, default=8)
    parser.add_argument("--max-trace-gap-s", type=float, default=2700)
    args = parser.parse_args()

    airport_index = AirportIndex.from_json(args.airport_index)
    airports = {airport.iata: airport for airport in airport_index.airports}
    route_specs = [_parse_route(value, airports) for value in args.routes]
    options = BuildOptions(min_points=args.min_points, max_trace_gap_s=args.max_trace_gap_s)

    releases = fetch_preferred_releases(args.year)
    entry = releases.get(args.date)
    if entry is None:
        raise SystemExit(f"No ADSB.lol preferred release found for {args.date}.")
    release_dir = args.work_dir / entry.date
    release_dir.mkdir(parents=True, exist_ok=True)
    parts = [_download_with_curl(url, release_dir) for url in entry.urls]

    result = scan_corridors(
        parts=parts,
        date=args.date,
        routes=route_specs,
        options=options,
        airport_index=airport_index,
        corridor_km=args.corridor_km,
        endpoint_km=args.endpoint_km,
        min_corridor_fraction=args.min_corridor_fraction,
        min_progress=args.min_progress,
        top=args.top,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    route_slug = "_".join(f"{origin.iata}-{destination.iata}" for origin, destination in route_specs)
    output = args.output_dir / f"{args.date}-corridor-{route_slug}.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": result["summary"]}, ensure_ascii=False, indent=2))
    return 0


def scan_corridors(
    parts: list[Path],
    date: str,
    routes: list[tuple[Airport, Airport]],
    options: BuildOptions,
    airport_index: AirportIndex,
    corridor_km: float,
    endpoint_km: float,
    min_corridor_fraction: float,
    min_progress: float,
    top: int,
) -> dict[str, Any]:
    summary: Counter[str] = Counter()
    callsigns: Counter[str] = Counter()
    fd_callsigns: Counter[str] = Counter()
    candidates: dict[str, list[dict[str, Any]]] = {f"{origin.iata}-{destination.iata}": [] for origin, destination in routes}

    for source_name, payload in iter_trace_payloads_from_split_tar(parts):
        summary["traces_seen"] += 1
        try:
            trace = json.loads(payload)
            points = parse_trace_points(trace)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            summary["parse_errors"] += 1
            continue
        legs = split_legs(points, options)
        for leg in legs:
            summary["legs_seen"] += 1
            callsign = _leg_callsign(leg) or trace.get("flight") or ""
            if callsign:
                callsigns[callsign] += 1
                if "FD" in callsign.upper() or "AIQ" in callsign.upper():
                    fd_callsigns[callsign] += 1
            for origin, destination in routes:
                match = _corridor_match(
                    leg=leg,
                    origin=origin,
                    destination=destination,
                    airport_index=airport_index,
                    corridor_km=corridor_km,
                    endpoint_km=endpoint_km,
                    min_corridor_fraction=min_corridor_fraction,
                    min_progress=min_progress,
                )
                if match is None:
                    continue
                summary[f"{origin.iata}-{destination.iata}_matches"] += 1
                match.update(
                    {
                        "callsign": callsign or None,
                        "sourceFile": source_name,
                        "points": len(leg),
                        "distanceKm": round(route_distance_km([(point.lat, point.lon) for point in leg]), 1),
                        "firstPoint": _point_payload(leg[0], origin, destination),
                        "lastPoint": _point_payload(leg[-1], origin, destination),
                    }
                )
                _push_candidate(candidates[f"{origin.iata}-{destination.iata}"], match, top)

    return {
        "schemaVersion": 1,
        "date": date,
        "routes": [f"{origin.iata}-{destination.iata}" for origin, destination in routes],
        "parameters": {
            "corridorKm": corridor_km,
            "endpointKm": endpoint_km,
            "minCorridorFraction": min_corridor_fraction,
            "minProgress": min_progress,
        },
        "summary": dict(summary),
        "fdOrAiqCallsigns": fd_callsigns.most_common(80),
        "topCallsigns": callsigns.most_common(80),
        "candidates": {
            route: sorted(items, key=lambda item: item["score"], reverse=True)[:top]
            for route, items in candidates.items()
        },
    }


def _corridor_match(
    leg: list[TracePoint],
    origin: Airport,
    destination: Airport,
    airport_index: AirportIndex,
    corridor_km: float,
    endpoint_km: float,
    min_corridor_fraction: float,
    min_progress: float,
) -> dict[str, Any] | None:
    metrics = [_project_point(point.lat, point.lon, origin, destination) for point in leg]
    in_corridor = [item for item in metrics if 0 <= item["t"] <= 1 and item["distanceKm"] <= corridor_km]
    if not in_corridor:
        return None
    fraction = len(in_corridor) / len(metrics)
    t_values = [item["t"] for item in in_corridor]
    progress = max(t_values) - min(t_values)
    first_origin = haversine_km(leg[0].lat, leg[0].lon, origin.lat, origin.lon)
    last_destination = haversine_km(leg[-1].lat, leg[-1].lon, destination.lat, destination.lon)
    first_destination = haversine_km(leg[0].lat, leg[0].lon, destination.lat, destination.lon)
    last_origin = haversine_km(leg[-1].lat, leg[-1].lon, origin.lat, origin.lon)
    forward = metrics[-1]["t"] >= metrics[0]["t"]
    endpoint_plausible = (
        (first_origin <= endpoint_km and last_destination <= endpoint_km)
        or (min(item["t"] for item in metrics) <= 0.18 and max(item["t"] for item in metrics) >= 0.82)
    )
    if fraction < min_corridor_fraction or progress < min_progress or not forward or not endpoint_plausible:
        return None
    nearest_first = airport_index.nearest(leg[0].lat, leg[0].lon, 300)
    nearest_last = airport_index.nearest(leg[-1].lat, leg[-1].lon, 300)
    score = fraction * 1000 + progress * 600
    score -= min(first_origin, endpoint_km) / 5
    score -= min(last_destination, endpoint_km) / 5
    return {
        "score": round(score, 2),
        "corridorFraction": round(fraction, 3),
        "progress": round(progress, 3),
        "tStart": round(metrics[0]["t"], 3),
        "tEnd": round(metrics[-1]["t"], 3),
        "tMin": round(min(item["t"] for item in metrics), 3),
        "tMax": round(max(item["t"] for item in metrics), 3),
        "minCorridorDistanceKm": round(min(item["distanceKm"] for item in metrics), 1),
        "medianCorridorDistanceKm": round(sorted(item["distanceKm"] for item in in_corridor)[len(in_corridor) // 2], 1),
        "firstOriginKm": round(first_origin, 1),
        "lastDestinationKm": round(last_destination, 1),
        "firstDestinationKm": round(first_destination, 1),
        "lastOriginKm": round(last_origin, 1),
        "nearestFirst": _nearest_payload(nearest_first),
        "nearestLast": _nearest_payload(nearest_last),
    }


def _project_point(lat: float, lon: float, origin: Airport, destination: Airport) -> dict[str, float]:
    mid_lat = math.radians((origin.lat + destination.lat) / 2)
    ax = 0.0
    ay = 0.0
    bx = (destination.lon - origin.lon) * 111.320 * math.cos(mid_lat)
    by = (destination.lat - origin.lat) * 110.574
    px = (lon - origin.lon) * 111.320 * math.cos(mid_lat)
    py = (lat - origin.lat) * 110.574
    vx = bx - ax
    vy = by - ay
    denom = vx * vx + vy * vy
    t = 0.0 if denom == 0 else ((px - ax) * vx + (py - ay) * vy) / denom
    nearest_x = ax + t * vx
    nearest_y = ay + t * vy
    distance = math.hypot(px - nearest_x, py - nearest_y)
    return {"t": t, "distanceKm": distance}


def _push_candidate(items: list[dict[str, Any]], candidate: dict[str, Any], top: int) -> None:
    items.append(candidate)
    if len(items) > top * 3:
        items.sort(key=lambda item: item["score"], reverse=True)
        del items[top:]


def _parse_route(value: str, airports: dict[str, Airport]) -> tuple[Airport, Airport]:
    parts = value.upper().split("-")
    if len(parts) != 2 or parts[0] not in airports or parts[1] not in airports:
        raise SystemExit(f"Unknown route: {value}")
    return airports[parts[0]], airports[parts[1]]


def _point_payload(point: TracePoint, origin: Airport, destination: Airport) -> dict[str, Any]:
    return {
        "lat": round(point.lat, 5),
        "lon": round(point.lon, 5),
        "elapsedS": point.elapsed_s,
        "altitudeFt": point.altitude_ft,
        "trackDeg": point.track_deg,
        "distanceToOriginKm": round(haversine_km(point.lat, point.lon, origin.lat, origin.lon), 1),
        "distanceToDestinationKm": round(haversine_km(point.lat, point.lon, destination.lat, destination.lon), 1),
    }


def _nearest_payload(nearest: Any) -> dict[str, Any] | None:
    if nearest is None:
        return None
    return {
        "iata": nearest.airport.iata,
        "icao": nearest.airport.icao,
        "name": nearest.airport.name,
        "distanceKm": round(nearest.distance_km, 1),
    }


def _leg_callsign(points: list[TracePoint]) -> str | None:
    for point in points:
        if point.callsign:
            return point.callsign
    return None


if __name__ == "__main__":
    raise SystemExit(main())
