#!/usr/bin/env python3
from __future__ import annotations

import argparse
import heapq
import json
import math
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
DEFAULT_AIRPORT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "airports-index.json"
DEFAULT_CONTEXT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "aviation-context-index.json"
DEFAULT_AIRGRAPH = ROOT / "shared" / "offline-packs" / "aviation" / "regions" / "global.airgraph.json"
DEFAULT_DIAGNOSTIC_DIR = PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "diagnostics"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit an OpenFlights airport pair against the airgraph route shape.")
    parser.add_argument("--route", required=True, help="Airport pair such as KHH-NRT.")
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--context-index", type=Path, default=DEFAULT_CONTEXT_INDEX)
    parser.add_argument("--airgraph", type=Path, default=DEFAULT_AIRGRAPH)
    parser.add_argument("--corridor-diagnostic", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    origin_iata, destination_iata = parse_route(args.route)
    airports = {
        airport["iataCode"]: airport
        for airport in json.loads(args.airport_index.read_text(encoding="utf-8")).get("airports", [])
        if airport.get("iataCode")
    }
    contexts = {
        context["iataCode"]: context
        for context in json.loads(args.context_index.read_text(encoding="utf-8")).get("contexts", [])
        if context.get("iataCode")
    }
    if origin_iata not in airports or destination_iata not in airports:
        raise SystemExit(f"Unknown route airport: {args.route}")

    openflights = lookup_openflights_pair(contexts, origin_iata, destination_iata)
    airgraph = json.loads(args.airgraph.read_text(encoding="utf-8"))
    airgraph_result = compute_airgraph_route(airgraph, airports[origin_iata], airports[destination_iata])
    corridor_result = load_corridor_support(args.corridor_diagnostic, args.route) if args.corridor_diagnostic else None
    adsb_shape_evaluation = evaluate_adsb_shape_support(corridor_result)
    report = {
        "schemaVersion": 1,
        "route": f"{origin_iata}-{destination_iata}",
        "pairSource": openflights,
        "airgraph": airgraph_result,
        "corridorDiagnostic": corridor_result,
        "adsbShapeEvaluation": adsb_shape_evaluation,
        "decision": decide_pair_shape(openflights, airgraph_result, adsb_shape_evaluation),
    }
    output = args.output or DEFAULT_DIAGNOSTIC_DIR / f"{origin_iata}-{destination_iata}-pair-airgraph-audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "decision": report["decision"]}, ensure_ascii=False, indent=2))
    return 0


def parse_route(route: str) -> tuple[str, str]:
    parts = route.strip().upper().split("-")
    if len(parts) != 2:
        raise SystemExit(f"Invalid route: {route}")
    return parts[0], parts[1]


def lookup_openflights_pair(contexts: dict[str, dict[str, Any]], origin: str, destination: str) -> dict[str, Any]:
    route_graph = (contexts.get(origin) or {}).get("routeGraph") or {}
    for destination_row in route_graph.get("destinations") or route_graph.get("topDestinations") or []:
        if destination_row.get("code") == destination:
            return {
                "exists": True,
                "source": route_graph.get("source"),
                "count": destination_row.get("count"),
                "aircraftTypes": destination_row.get("aircraftTypes") or [],
                "airlines": route_graph.get("airlines") or [],
            }
    return {"exists": False}


def compute_airgraph_route(pack: dict[str, Any], origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, Any]:
    points = pack["points"]
    graph = build_graph(pack)
    origin_connector = nearest_airgraph_point(pack, origin)
    destination_connector = nearest_airgraph_point(pack, destination)
    if origin_connector is None or destination_connector is None:
        return {"exists": False, "reason": "connector_missing"}
    path = shortest_path(graph, origin_connector["index"], destination_connector["index"])
    if not path:
        return {"exists": False, "reason": "path_missing"}
    route_points = [airport_point(origin), *[point_payload(points[index]) for index in path], airport_point(destination)]
    distance_km = route_distance_km(route_points)
    direct_km = haversine_km(origin["latitude"], origin["longitude"], destination["latitude"], destination["longitude"])
    return {
        "exists": True,
        "originConnector": connector_payload(points, origin_connector),
        "destinationConnector": connector_payload(points, destination_connector),
        "waypointCount": len(path),
        "distanceKm": round(distance_km, 1),
        "directKm": round(direct_km, 1),
        "detourRatio": round(distance_km / direct_km, 3) if direct_km else None,
        "firstWaypoints": [point_payload(points[index]) for index in path[:12]],
        "taiwanSideHeuristic": taiwan_side_heuristic(points, path),
    }


def build_graph(pack: dict[str, Any]) -> list[list[tuple[int, float]]]:
    graph: list[list[tuple[int, float]]] = [[] for _ in pack["points"]]
    for from_idx, to_idx, _, distance_nm, _ in pack["segments"]:
        distance_km = float(distance_nm) * 1.852
        graph[from_idx].append((to_idx, distance_km))
        graph[to_idx].append((from_idx, distance_km))
    return graph


def nearest_airgraph_point(pack: dict[str, Any], airport: dict[str, Any]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for index, point in enumerate(pack["points"]):
        distance = haversine_km(airport["latitude"], airport["longitude"], point[1], point[2])
        if best is None or distance < best["distanceKm"]:
            best = {"index": index, "distanceKm": distance}
    return best


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


def load_corridor_support(path: Path, route: str) -> dict[str, Any]:
    diagnostic = json.loads(path.read_text(encoding="utf-8"))
    candidates = diagnostic.get("candidates", {}).get(route, [])
    return {
        "date": diagnostic.get("date"),
        "candidates": len(candidates),
        "topCandidates": candidates[:50],
    }


def evaluate_adsb_shape_support(corridor: dict[str, Any] | None) -> dict[str, Any]:
    if corridor is None:
        return {
            "adsbSupported": False,
            "reason": "no_corridor_diagnostic",
            "strictOriginDestinationCandidates": 0,
        }
    strict = []
    rejected_counts: dict[str, int] = {}
    for candidate in corridor.get("topCandidates", []):
        reasons = adsb_rejection_reasons(candidate)
        if reasons:
            for reason in reasons:
                rejected_counts[reason] = rejected_counts.get(reason, 0) + 1
        else:
            strict.append(candidate)
    strict.sort(key=lambda item: item.get("score") or 0, reverse=True)
    return {
        "adsbSupported": bool(strict),
        "reason": "strict_adsb_pair_candidates_found" if strict else "no_strict_adsb_pair_candidates",
        "corridorCandidates": corridor.get("candidates", 0),
        "strictOriginDestinationCandidates": len(strict),
        "topStrictCandidates": strict[:10],
        "topRejectReasons": sorted(rejected_counts.items(), key=lambda item: item[1], reverse=True)[:20],
    }


def adsb_rejection_reasons(candidate: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    nearest_first = (candidate.get("nearestFirst") or {}).get("iata")
    nearest_last = (candidate.get("nearestLast") or {}).get("iata")
    if candidate.get("firstOriginKm", 999999) > 220:
        reasons.append("first_point_too_far_from_pair_origin")
    if candidate.get("lastDestinationKm", 999999) > 120:
        reasons.append("last_point_too_far_from_pair_destination")
    if candidate.get("corridorFraction", 0) < 0.55:
        reasons.append("corridor_fraction_too_low")
    if candidate.get("progress", 0) < 0.55:
        reasons.append("route_progress_too_low")
    if nearest_first in {"TPE", "TSA", "RMQ", "OGN", "ISG"}:
        reasons.append("nearest_first_is_competing_airport")
    if nearest_last not in {None, "NRT"}:
        reasons.append("nearest_last_is_not_pair_destination")
    return reasons


def decide_pair_shape(
    openflights: dict[str, Any],
    airgraph: dict[str, Any],
    adsb_shape_evaluation: dict[str, Any],
) -> dict[str, Any]:
    if not openflights.get("exists"):
        return {"usable": False, "reason": "airport_pair_not_in_static_route_graph"}
    if not airgraph.get("exists"):
        return {"usable": False, "reason": airgraph.get("reason", "airgraph_missing")}
    if (airgraph.get("originConnector") or {}).get("distanceKm", 999999) > 80:
        return {"usable": False, "reason": "origin_airgraph_connector_too_far"}
    if (airgraph.get("destinationConnector") or {}).get("distanceKm", 999999) > 80:
        return {"usable": False, "reason": "destination_airgraph_connector_too_far"}
    if airgraph.get("detourRatio", 999999) > 1.35:
        return {"usable": False, "reason": "airgraph_detour_too_high"}
    if adsb_shape_evaluation.get("adsbSupported"):
        return {"usable": True, "confidence": "static_pair_plus_airgraph_plus_adsb_shape_support"}
    if adsb_shape_evaluation.get("corridorCandidates", 0) > 0:
        return {
            "usable": True,
            "confidence": "static_pair_plus_airgraph_only_adsb_rejected",
            "warning": "ADSB corridor candidates exist but none pass strict airport-pair origin/destination checks.",
        }
    return {"usable": True, "confidence": "static_pair_plus_airgraph"}


def airport_point(airport: dict[str, Any]) -> dict[str, Any]:
    return {"ident": airport["iataCode"], "lat": airport["latitude"], "lon": airport["longitude"], "pointType": "AIRPORT"}


def point_payload(row: list[Any]) -> dict[str, Any]:
    return {"ident": row[0], "lat": row[1], "lon": row[2], "pointType": row[3]}


def connector_payload(points: list[list[Any]], connector: dict[str, Any]) -> dict[str, Any]:
    point = points[connector["index"]]
    payload = point_payload(point)
    payload["distanceKm"] = round(connector["distanceKm"], 1)
    return payload


def route_distance_km(points: list[dict[str, Any]]) -> float:
    total = 0.0
    for index in range(1, len(points)):
        total += haversine_km(points[index - 1]["lat"], points[index - 1]["lon"], points[index]["lat"], points[index]["lon"])
    return total


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1 = math.radians(lat1)
    rlon1 = math.radians(lon1)
    rlat2 = math.radians(lat2)
    rlon2 = math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    value = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1, math.sqrt(value)))


def taiwan_side_heuristic(points: list[list[Any]], path: list[int]) -> list[dict[str, Any]]:
    rows = []
    for index in path:
        point = points[index]
        lat = point[1]
        lon = point[2]
        if 21.5 <= lat <= 26.5:
            rows.append(
                {
                    "ident": point[0],
                    "lat": lat,
                    "lon": lon,
                    "side": "west_or_strait" if lon < 120.9 else "east",
                }
            )
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
