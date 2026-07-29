#!/usr/bin/env python3
from __future__ import annotations

import argparse
import heapq
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
DEFAULT_AIRPORT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "airports-index.json"
DEFAULT_CONTEXT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "aviation-context-index.json"
DEFAULT_AIRGRAPH = ROOT / "shared" / "offline-packs" / "aviation" / "regions" / "global.airgraph.json"
DEFAULT_OUTPUT_DIR = PROJECT / "data" / "releases" / "private" / "route-shape-selection"
DEFAULT_SHARED_DIR = ROOT / "shared" / "offline-packs" / "route-shapes"
DEFAULT_PUBLIC_DIR = ROOT / "replay-engine" / "public" / "offline-packs" / "route-shapes"


def main() -> int:
    parser = argparse.ArgumentParser(description="Select the best offline route shape for an airport pair.")
    parser.add_argument("--route", required=True, help="Airport pair, for example KHH-NRT.")
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--context-index", type=Path, default=DEFAULT_CONTEXT_INDEX)
    parser.add_argument("--airgraph", type=Path, default=DEFAULT_AIRGRAPH)
    parser.add_argument("--corridor-diagnostic", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--shared-dir", type=Path, default=DEFAULT_SHARED_DIR)
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    args = parser.parse_args()

    origin_iata, destination_iata = parse_route(args.route)
    airports = airport_lookup(args.airport_index)
    contexts = context_lookup(args.context_index)
    if origin_iata not in airports or destination_iata not in airports:
        raise SystemExit(f"Unknown route: {args.route}")

    origin = airports[origin_iata]
    destination = airports[destination_iata]
    pair_source = lookup_static_pair(contexts, origin_iata, destination_iata)
    airgraph_pack = json.loads(args.airgraph.read_text(encoding="utf-8"))
    airgraph_candidate = build_airgraph_candidate(airgraph_pack, origin, destination)
    great_circle_waypoint_candidate = build_great_circle_waypoint_candidate(airgraph_pack, origin, destination)
    great_circle_candidate = build_great_circle_candidate(origin, destination)
    adsb_support = load_adsb_support(args.corridor_diagnostic, args.route) if args.corridor_diagnostic else no_adsb_support()

    candidates = [candidate for candidate in [airgraph_candidate, great_circle_waypoint_candidate, great_circle_candidate] if candidate]
    for candidate in candidates:
        score_candidate(candidate, origin, destination, pair_source, adsb_support)
    candidates.sort(key=lambda item: item["score"], reverse=True)
    selected = candidates[0]
    result = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "route": f"{origin_iata}-{destination_iata}",
        "pairSource": pair_source,
        "adsbSupport": adsb_support,
        "selected": {
            "method": selected["method"],
            "score": selected["score"],
            "reason": selected["selectionReason"],
            "provenance": selected["provenance"],
            "points": selected["points"],
            "metrics": selected["metrics"],
        },
        "candidates": candidates,
    }
    write_outputs(result, args.output_dir, args.shared_dir, args.public_dir)
    print(
        json.dumps(
            {
                "route": result["route"],
                "selected": result["selected"]["method"],
                "score": result["selected"]["score"],
                "reason": result["selected"]["reason"],
                "output": str(args.output_dir / f"{result['route']}.shape-selection.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_route(route: str) -> tuple[str, str]:
    parts = route.strip().upper().split("-")
    if len(parts) != 2:
        raise SystemExit(f"Invalid route: {route}")
    return parts[0], parts[1]


def airport_lookup(path: Path) -> dict[str, dict[str, Any]]:
    return {
        airport["iataCode"]: airport
        for airport in json.loads(path.read_text(encoding="utf-8")).get("airports", [])
        if airport.get("iataCode")
    }


def context_lookup(path: Path) -> dict[str, dict[str, Any]]:
    return {
        context["iataCode"]: context
        for context in json.loads(path.read_text(encoding="utf-8")).get("contexts", [])
        if context.get("iataCode")
    }


def lookup_static_pair(contexts: dict[str, dict[str, Any]], origin: str, destination: str) -> dict[str, Any]:
    graph = (contexts.get(origin) or {}).get("routeGraph") or {}
    for row in graph.get("destinations") or graph.get("topDestinations") or []:
        if row.get("code") == destination:
            return {
                "exists": True,
                "source": graph.get("source"),
                "count": int(row.get("count") or 0),
                "aircraftTypes": row.get("aircraftTypes") or [],
            }
    return {"exists": False}


def build_airgraph_candidate(
    pack: dict[str, Any],
    origin: dict[str, Any],
    destination: dict[str, Any],
) -> dict[str, Any] | None:
    points = pack["points"]
    origin_connector = nearest_point(points, origin)
    destination_connector = nearest_point(points, destination)
    graph = build_graph(pack)
    path = shortest_path(graph, origin_connector["index"], destination_connector["index"])
    if not path:
        return None
    route_points = [airport_point(origin), *[pack_point(points[index]) for index in path], airport_point(destination)]
    return {
        "method": "airgraph_shortest_path",
        "provenance": {
            "source": "aviationdb-airgraph",
            "originConnector": {**pack_point(points[origin_connector["index"]]), "distanceKm": round(origin_connector["distanceKm"], 1)},
            "destinationConnector": {
                **pack_point(points[destination_connector["index"]]),
                "distanceKm": round(destination_connector["distanceKm"], 1),
            },
            "waypointCount": len(path),
        },
        "points": route_points,
    }


def build_great_circle_candidate(origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, Any]:
    return {
        "method": "great_circle_pair_fallback",
        "provenance": {
            "source": "openflights-pair-plus-great-circle",
            "note": "Selected when airgraph shortest path conflicts with great-circle/ADSB scoring.",
        },
        "points": [
            {
                "ident": f"GC{index:02d}" if 0 < index < 12 else (origin["iataCode"] if index == 0 else destination["iataCode"]),
                "lat": round(point["lat"], 6),
                "lon": round(point["lon"], 6),
                "pointType": "AIRPORT" if index in {0, 12} else "GREAT_CIRCLE_INTERPOLATED",
            }
            for index, point in enumerate(interpolate_great_circle(origin, destination, steps=12))
        ],
    }


def build_great_circle_waypoint_candidate(
    pack: dict[str, Any],
    origin: dict[str, Any],
    destination: dict[str, Any],
) -> dict[str, Any] | None:
    selected: list[dict[str, Any]] = []
    last_t = 0.0
    for target_t in [index / 10 for index in range(1, 10)]:
        best: dict[str, Any] | None = None
        for row in pack["points"]:
            point = pack_point(row)
            projection = project_distance_km(point["lat"], point["lon"], origin, destination)
            t = projection["t"]
            if not 0.04 <= t <= 0.96:
                continue
            if projection["distanceKm"] > 180:
                continue
            # Keep the route moving forward and avoid choosing several points from the same local cluster.
            if selected and t <= last_t + 0.035:
                continue
            target_delta = abs(t - target_t)
            rank = projection["distanceKm"] + target_delta * 260
            if best is None or rank < best["rank"]:
                best = {
                    **point,
                    "rank": rank,
                    "greatCircleT": round(t, 3),
                    "greatCircleDistanceKm": round(projection["distanceKm"], 1),
                }
        if best is None:
            continue
        selected.append({key: value for key, value in best.items() if key != "rank"})
        last_t = float(best["greatCircleT"])
    if len(selected) < 4:
        return None
    points = [airport_point(origin), *selected, airport_point(destination)]
    return {
        "method": "great_circle_waypoint_corridor",
        "provenance": {
            "source": "openflights-pair-plus-airgraph-waypoints-near-great-circle",
            "note": "Uses real airgraph waypoints selected by proximity to the airport-pair great-circle corridor; airway segment connectivity is not implied.",
            "waypointCount": len(selected),
            "maxWaypointCorridorKm": max(point["greatCircleDistanceKm"] for point in selected),
        },
        "points": points,
    }


def build_graph(pack: dict[str, Any]) -> list[list[tuple[int, float]]]:
    graph: list[list[tuple[int, float]]] = [[] for _ in pack["points"]]
    for from_idx, to_idx, _, distance_nm, _ in pack["segments"]:
        distance_km = float(distance_nm) * 1.852
        graph[from_idx].append((to_idx, distance_km))
        graph[to_idx].append((from_idx, distance_km))
    return graph


def shortest_path(graph: list[list[tuple[int, float]]], start: int, goal: int) -> list[int]:
    distances = {start: 0.0}
    previous: dict[int, int | None] = {start: None}
    queue = [(0.0, start)]
    while queue:
        distance, node = heapq.heappop(queue)
        if node == goal:
            break
        if distance > distances.get(node, math.inf):
            continue
        for next_node, weight in graph[node]:
            candidate = distance + weight
            if candidate < distances.get(next_node, math.inf):
                distances[next_node] = candidate
                previous[next_node] = node
                heapq.heappush(queue, (candidate, next_node))
    if goal not in previous:
        return []
    path = []
    cursor: int | None = goal
    while cursor is not None:
        path.append(cursor)
        cursor = previous[cursor]
    return path[::-1]


def nearest_point(points: list[list[Any]], airport: dict[str, Any]) -> dict[str, Any]:
    best = {"index": 0, "distanceKm": math.inf}
    for index, point in enumerate(points):
        distance = haversine_km(airport["latitude"], airport["longitude"], point[1], point[2])
        if distance < best["distanceKm"]:
            best = {"index": index, "distanceKm": distance}
    return best


def score_candidate(
    candidate: dict[str, Any],
    origin: dict[str, Any],
    destination: dict[str, Any],
    pair_source: dict[str, Any],
    adsb_support: dict[str, Any],
) -> None:
    points = candidate["points"]
    direct_km = haversine_km(origin["latitude"], origin["longitude"], destination["latitude"], destination["longitude"])
    distance_km = route_distance_km(points)
    detour_ratio = distance_km / direct_km if direct_km else math.inf
    deviation = great_circle_deviation(points, origin, destination)
    south_penalty_km = max(0.0, (origin["latitude"] - min(point["lat"] for point in points)) * 110.574)
    early_east_penalty_km = early_east_penalty(points, origin, destination)
    score = 100.0
    score -= max(0.0, detour_ratio - 1.05) * 160
    score -= deviation["meanKm"] * 0.7
    score -= deviation["maxKm"] * 0.2
    score -= south_penalty_km * 0.25
    score -= early_east_penalty_km * 0.18
    if pair_source.get("exists"):
        score += 12
    if adsb_support.get("strictOriginDestinationCandidates", 0) > 0:
        score += 20
    if candidate["method"] == "airgraph_shortest_path":
        score += 5
    if candidate["method"] == "great_circle_waypoint_corridor":
        score += 8
    if candidate["method"] == "great_circle_pair_fallback":
        score -= 3
    metrics = {
        "distanceKm": round(distance_km, 1),
        "directKm": round(direct_km, 1),
        "detourRatio": round(detour_ratio, 3),
        "greatCircleMeanDeviationKm": round(deviation["meanKm"], 1),
        "greatCircleMaxDeviationKm": round(deviation["maxKm"], 1),
        "southPenaltyKm": round(south_penalty_km, 1),
        "earlyEastPenaltyKm": round(early_east_penalty_km, 1),
        "taiwanSideHeuristic": taiwan_side_heuristic(points),
    }
    candidate["metrics"] = metrics
    candidate["score"] = round(score, 2)
    candidate["selectionReason"] = selection_reason(candidate)


def selection_reason(candidate: dict[str, Any]) -> str:
    if candidate["method"] == "great_circle_pair_fallback":
        return "Great-circle pair fallback has lower detour/south/east penalty than available airgraph path."
    if candidate["method"] == "great_circle_waypoint_corridor":
        return "Real airgraph waypoints near the airport-pair great-circle corridor score best."
    return "Airgraph path remains close enough to great-circle scoring."


def great_circle_deviation(points: list[dict[str, Any]], origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, float]:
    deviations = [project_distance_km(point["lat"], point["lon"], origin, destination)["distanceKm"] for point in points]
    return {"meanKm": sum(deviations) / len(deviations), "maxKm": max(deviations)}


def early_east_penalty(points: list[dict[str, Any]], origin: dict[str, Any], destination: dict[str, Any]) -> float:
    penalty = 0.0
    for point in points:
        projection = project_distance_km(point["lat"], point["lon"], origin, destination)
        if 0 <= projection["t"] <= 0.28:
            gc_point = interpolate_linear_local(origin, destination, projection["t"])
            east_km = max(0.0, (point["lon"] - gc_point["lon"]) * 111.320 * math.cos(math.radians(point["lat"])))
            penalty = max(penalty, east_km)
    return penalty


def project_distance_km(lat: float, lon: float, origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, float]:
    mid_lat = math.radians((origin["latitude"] + destination["latitude"]) / 2)
    bx = (destination["longitude"] - origin["longitude"]) * 111.320 * math.cos(mid_lat)
    by = (destination["latitude"] - origin["latitude"]) * 110.574
    px = (lon - origin["longitude"]) * 111.320 * math.cos(mid_lat)
    py = (lat - origin["latitude"]) * 110.574
    denom = bx * bx + by * by
    t = 0.0 if denom == 0 else (px * bx + py * by) / denom
    nearest_x = t * bx
    nearest_y = t * by
    return {"t": t, "distanceKm": math.hypot(px - nearest_x, py - nearest_y)}


def interpolate_linear_local(origin: dict[str, Any], destination: dict[str, Any], fraction: float) -> dict[str, float]:
    return {
        "lat": origin["latitude"] + (destination["latitude"] - origin["latitude"]) * fraction,
        "lon": origin["longitude"] + (destination["longitude"] - origin["longitude"]) * fraction,
    }


def interpolate_great_circle(origin: dict[str, Any], destination: dict[str, Any], steps: int) -> list[dict[str, float]]:
    lat1 = math.radians(origin["latitude"])
    lon1 = math.radians(origin["longitude"])
    lat2 = math.radians(destination["latitude"])
    lon2 = math.radians(destination["longitude"])
    delta = 2 * math.asin(
        math.sqrt(
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        )
    )
    points = []
    for index in range(steps + 1):
        fraction = index / steps
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


def load_adsb_support(path: Path, route: str) -> dict[str, Any]:
    diagnostic = json.loads(path.read_text(encoding="utf-8"))
    candidates = diagnostic.get("candidates", {}).get(route, [])
    strict = [
        candidate
        for candidate in candidates
        if candidate.get("firstOriginKm", 999999) <= 220
        and candidate.get("lastDestinationKm", 999999) <= 120
        and (candidate.get("nearestFirst") or {}).get("iata") not in {"TPE", "TSA", "RMQ", "OGN", "ISG"}
    ]
    return {
        "diagnosticDate": diagnostic.get("date"),
        "corridorCandidates": len(candidates),
        "strictOriginDestinationCandidates": len(strict),
    }


def no_adsb_support() -> dict[str, Any]:
    return {"corridorCandidates": 0, "strictOriginDestinationCandidates": 0}


def airport_point(airport: dict[str, Any]) -> dict[str, Any]:
    return {"ident": airport["iataCode"], "lat": airport["latitude"], "lon": airport["longitude"], "pointType": "AIRPORT"}


def pack_point(row: list[Any]) -> dict[str, Any]:
    return {"ident": row[0], "lat": row[1], "lon": row[2], "pointType": row[3]}


def route_distance_km(points: list[dict[str, Any]]) -> float:
    return sum(
        haversine_km(points[index - 1]["lat"], points[index - 1]["lon"], points[index]["lat"], points[index]["lon"])
        for index in range(1, len(points))
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1 = math.radians(lat1)
    rlon1 = math.radians(lon1)
    rlat2 = math.radians(lat2)
    rlon2 = math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    value = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1, math.sqrt(value)))


def taiwan_side_heuristic(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "ident": point["ident"],
            "lat": point["lat"],
            "lon": point["lon"],
            "side": "west_or_strait" if point["lon"] < 120.9 else "east",
        }
        for point in points
        if 21.5 <= point["lat"] <= 26.5
    ]


def write_outputs(result: dict[str, Any], output_dir: Path, shared_dir: Path, public_dir: Path) -> None:
    filename = f"{result['route']}.shape-selection.json"
    for directory in [output_dir, shared_dir, public_dir]:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
