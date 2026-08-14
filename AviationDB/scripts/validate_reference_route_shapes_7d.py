#!/usr/bin/env python3
"""Validate the geometry of the reference corridor paths.

This report is deliberately separate from airport-pair connectivity QA.  It
does not claim that a path is a callsign-specific ADS-B trace.  It measures
whether the selected corridor path has plausible great-circle progress,
reasonable detour, and a continuous 0.25-degree geometry, while identifying
which links are inferred relays.
"""

from __future__ import annotations

import argparse
import gzip
import heapq
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PAIRS = [
    ("CI8", "TPE", "LAX"),
    ("AC66", "TPE", "YVR"),
    ("QF5", "SYD", "FCO"),
    ("QF11", "SYD", "LAX"),
    ("FD234", "DMK", "KHH"),
    ("FD234", "KHH", "NRT"),
    ("JX101", "TPE", "PRG"),
    ("AZ793", "HND", "FCO"),
]
CELL_DEG = 0.25
LON_CELL_COUNT = round(360.0 / CELL_DEG)
MAX_LOCAL_EDGE_KM = 180.0
MAX_LOCAL_EDGE_JUMP_CELLS = 4
MAX_ROUTE_CORRIDOR_CROSS_TRACK_KM = 1800.0
ROUTE_CORRIDOR_ALONG_MIN = -0.15
ROUTE_CORRIDOR_ALONG_MAX = 1.15
EARTH_RADIUS_KM = 6371.0088
AIRPORT_PREFIX = "airport:"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs-file", type=Path)
    args = parser.parse_args()

    network = read_gzip(args.network)
    audit = read_gzip(args.audit)
    graph, edge_meta = build_graph(network, audit)
    airport_access = {
        str(item.get("iataCode") or "").upper(): item
        for item in audit.get("airportAccess", [])
    }

    pairs = load_pairs(args.pairs_file) if args.pairs_file else [
        {"callsignReference": callsign, "origin": origin, "destination": destination}
        for callsign, origin, destination in PAIRS
    ]
    results = []
    for pair in pairs:
        result = validate_pair(
            str(pair.get("callsignReference") or "raw-derived-endpoint-candidate"),
            str(pair["origin"]).upper(),
            str(pair["destination"]).upper(),
            graph,
            edge_meta,
            airport_access,
            pair,
        )
        results.append(result)

    payload = {
        "schemaVersion": 1,
        "evidenceType": "reference_route_shape_qa_v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "method": {
            "pathSelection": "weighted shortest path over observed edges plus explicitly tagged inferred relays and airport access",
            "cellDegrees": CELL_DEG,
            "greatCircleComparison": True,
            "callsignSpecificAdsBClaim": False,
            "thresholds": {
                "maxDetourRatio": 1.45,
                "maxCrossTrackKm": 1800.0,
                "routeCorridorCrossTrackKm": MAX_ROUTE_CORRIDOR_CROSS_TRACK_KM,
                "routeCorridorAlongFraction": [ROUTE_CORRIDOR_ALONG_MIN, ROUTE_CORRIDOR_ALONG_MAX],
                "minProgressFraction": 0.70,
                "maxNonProgressiveFraction": 0.35,
                "maxLocalEdgeDistanceKm": MAX_LOCAL_EDGE_KM,
                "maxLocalEdgeJumpCells": MAX_LOCAL_EDGE_JUMP_CELLS,
            },
        },
        "pairs": results,
        "qa": {
            "passed": all(item["shapeQaPassed"] for item in results),
            "samplePassCount": sum(item["shapeQaPassed"] for item in results),
            "sampleFailCount": sum(not item["shapeQaPassed"] for item in results),
            "samplePassRate": round(sum(item["shapeQaPassed"] for item in results) / len(results), 4) if results else 0.0,
            "failedSampleIds": [
                item.get("sample", {}).get("sampleId")
                for item in results
                if not item["shapeQaPassed"]
            ],
            "checks": {
                "allPairsHavePath": all(item["pathFound"] for item in results),
                "allPathsAreContinuous025Degree": all(item["continuous025Degree"] for item in results),
                "allPathsHavePlausibleGreatCircleProgress": all(item["greatCircleProgressPlausible"] for item in results),
                "allPathsHaveReasonableDetour": all(item["reasonableDetour"] for item in results),
                "allPathsHaveBoundedCrossTrack": all(item["boundedCrossTrack"] for item in results),
            "inferredGeometryRemainSeparated": True,
            "callsignSpecificAdsBClaimSuppressed": True,
            "pairsFile": str(args.pairs_file) if args.pairs_file else None,
            "selectedPairCount": len(pairs),
        },
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": "complete", "qa": payload["qa"], "pairs": results}, ensure_ascii=False, indent=2))
    return 0 if payload["qa"]["passed"] else 2


def read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def load_pairs(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("selected") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"Pairs file has no selected samples: {path}")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        origin = str(row.get("origin") or row.get("originIata") or "").upper()
        destination = str(row.get("destination") or row.get("destinationIata") or "").upper()
        if not origin or not destination or origin == destination or (origin, destination) in seen:
            continue
        item = dict(row)
        item["origin"] = origin
        item["destination"] = destination
        result.append(item)
        seen.add((origin, destination))
    if not result:
        raise ValueError(f"Pairs file has no valid selected samples: {path}")
    return result


def node_key(node: dict[str, Any]) -> str:
    return f"{int(node['latCell'])}:{int(node['lonCell'])}"


def cell_center(key: str) -> tuple[float, float]:
    lat_cell, lon_cell = (int(value) for value in key.split(":"))
    return (
        lat_cell * CELL_DEG - 90.0 + CELL_DEG / 2.0,
        lon_cell * CELL_DEG - 180.0 + CELL_DEG / 2.0,
    )


def build_graph(
    network: dict[str, Any], audit: dict[str, Any]
) -> tuple[dict[str, dict[str, float]], dict[tuple[str, str], dict[str, Any]]]:
    graph: dict[str, dict[str, float]] = defaultdict(dict)
    edge_meta: dict[tuple[str, str], dict[str, Any]] = {}

    def add_edge(left: str, right: str, distance_km: float, kind: str, source: str) -> None:
        if left == right:
            return
        weight = max(float(distance_km), 0.001)
        if right not in graph[left] or weight < graph[left][right]:
            graph[left][right] = weight
            graph[right][left] = weight
            metadata = {"kind": kind, "source": source, "distanceKm": round(weight, 3)}
            edge_meta[(left, right)] = metadata
            edge_meta[(right, left)] = metadata

    for edge in network.get("observedEdges", []):
        left = node_key(edge["from"])
        right = node_key(edge["to"])
        distance = haversine(*cell_center(left), *cell_center(right))
        add_edge(left, right, distance, "observed", ",".join(edge.get("sources") or []))

    for link in network.get("relayInferred", []):
        left = node_key(link["from"])
        right = node_key(link["to"])
        add_edge(left, right, link.get("distanceKm") or haversine(*cell_center(left), *cell_center(right)), "relay_inferred", link.get("source", ""))

    for item in audit.get("airportAccess", []):
        code = str(item.get("iataCode") or "").upper()
        if not code:
            continue
        airport = AIRPORT_PREFIX + code
        for link in item.get("links", []):
            add_edge(airport, node_key(link["node"]), link.get("distanceKm") or 0.001, "airport_access_inferred", link.get("status", ""))
    return graph, edge_meta


def validate_pair(
    callsign: str,
    origin: str,
    destination: str,
    graph: dict[str, dict[str, float]],
    edge_meta: dict[tuple[str, str], dict[str, Any]],
    airports: dict[str, dict[str, Any]],
    sample: dict[str, Any] | None = None,
) -> dict[str, Any]:
    start = AIRPORT_PREFIX + origin
    target = AIRPORT_PREFIX + destination
    start_point = (float(airports[origin]["latitude"]), float(airports[origin]["longitude"]))
    end_point = (float(airports[destination]["latitude"]), float(airports[destination]["longitude"]))
    path, total_weight = shortest_path(graph, start, target, start_point, end_point)
    if not path:
        return {
            "callsignReference": callsign,
            "origin": origin,
            "destination": destination,
            "sample": sample or {},
            "pathFound": False,
            "shapeQaPassed": False,
            "continuous025Degree": False,
            "greatCircleProgressPlausible": False,
            "reasonableDetour": False,
            "boundedCrossTrack": False,
            "metrics": {
                "pathNodeCount": 0,
                "geometryPointCount": 0,
                "observedEdgeCount": 0,
                "relayInferredEdgeCount": 0,
                "airportAccessEdgeCount": 0,
                "discontinuityCount": 0,
            },
            "geometryGaps": [],
            "inference": {
                "usesInferredRelay": False,
                "usesInferredAirportAccess": False,
                "callsignSpecificAdsBProof": False,
            },
        }

    points = [(float(airports[origin]["latitude"]), float(airports[origin]["longitude"]))]
    for key in path[1:-1]:
        if not key.startswith(AIRPORT_PREFIX):
            points.append(cell_center(key))
    points.append((float(airports[destination]["latitude"]), float(airports[destination]["longitude"])))

    edge_kinds = []
    for left, right in zip(path, path[1:]):
        edge_kinds.append(edge_meta.get((left, right), {"kind": "unknown", "source": ""}))
    observed_edges = sum(item.get("kind") == "observed" for item in edge_kinds)
    relay_edges = sum(item.get("kind") == "relay_inferred" for item in edge_kinds)
    airport_edges = sum(item.get("kind") == "airport_access_inferred" for item in edge_kinds)

    start_point = points[0]
    end_point = points[-1]
    great_circle_km = haversine(*start_point, *end_point)
    path_length_km = sum(haversine(*left, *right) for left, right in zip(points, points[1:]))
    detour_ratio = path_length_km / great_circle_km if great_circle_km else float("inf")
    cross_track = [cross_track_km(start_point, end_point, point) for point in points]
    along = [along_track_fraction(start_point, end_point, point) for point in points]
    non_progressive = sum(right + 0.03 < left for left, right in zip(along, along[1:]))
    segment_count = max(len(points) - 1, 1)
    non_progressive_fraction = non_progressive / segment_count
    max_cross_track = max(cross_track, default=0.0)
    progress_fraction = max(along, default=0.0)
    cell_jumps = [
        (left, right, cell_jump(left, right))
        for left, right in zip(path, path[1:])
        if not left.startswith(AIRPORT_PREFIX) and not right.startswith(AIRPORT_PREFIX)
    ]
    jumps = [item[2] for item in cell_jumps]
    continuous = all(
        max(abs(a), abs(b)) <= MAX_LOCAL_EDGE_JUMP_CELLS
        and haversine(*cell_center(left), *cell_center(right)) <= MAX_LOCAL_EDGE_KM
        for left, right, (a, b) in cell_jumps
    )
    reasonable_detour = detour_ratio <= 1.45
    bounded_cross_track = max_cross_track <= 1800.0
    progress_plausible = progress_fraction >= 0.70 and non_progressive_fraction <= 0.35
    discontinuities = []
    for left, right, (lat_jump, lon_jump) in cell_jumps:
        cell_gap = max(abs(lat_jump), abs(lon_jump))
        edge_distance = haversine(*cell_center(left), *cell_center(right))
        if cell_gap > MAX_LOCAL_EDGE_JUMP_CELLS or edge_distance > MAX_LOCAL_EDGE_KM:
            metadata = edge_meta.get((left, right), {})
            discontinuities.append({
                "from": [round(value, 4) for value in cell_center(left)],
                "to": [round(value, 4) for value in cell_center(right)],
                "cellJump": [lat_jump, lon_jump],
                "maxCellGap": cell_gap,
                "distanceKm": round(edge_distance, 3),
                "kind": metadata.get("kind", "unknown"),
                "source": metadata.get("source", ""),
                "sourceDistanceKm": metadata.get("distanceKm"),
            })
    discontinuities.sort(key=lambda item: item["maxCellGap"], reverse=True)

    return {
        "callsignReference": callsign,
        "origin": origin,
        "destination": destination,
        "sample": sample or {},
        "pathFound": True,
        "shapeQaPassed": continuous and reasonable_detour and bounded_cross_track and progress_plausible,
        "continuous025Degree": continuous,
        "greatCircleProgressPlausible": progress_plausible,
        "reasonableDetour": reasonable_detour,
        "boundedCrossTrack": bounded_cross_track,
        "metrics": {
            "pathNodeCount": len(path),
            "geometryPointCount": len(points),
            "observedEdgeCount": observed_edges,
            "relayInferredEdgeCount": relay_edges,
            "airportAccessEdgeCount": airport_edges,
            "greatCircleDistanceKm": round(great_circle_km, 1),
            "pathLengthKm": round(path_length_km, 1),
            "detourRatio": round(detour_ratio, 4),
            "maxCrossTrackKm": round(max_cross_track, 1),
            "progressFraction": round(progress_fraction, 4),
            "nonProgressiveFraction": round(non_progressive_fraction, 4),
            "maxCellJump": max((max(abs(a), abs(b)) for a, b in jumps), default=0),
            "discontinuityCount": len(discontinuities),
        },
        "geometryGaps": discontinuities[:12],
        "geometry": {
            "start": [round(start_point[0], 5), round(start_point[1], 5)],
            "end": [round(end_point[0], 5), round(end_point[1], 5)],
            "sampledPoints": [[round(lat, 4), round(lon, 4)] for lat, lon in points[::max(1, len(points) // 24)]],
        },
        "inference": {
            "usesInferredRelay": relay_edges > 0,
            "usesInferredAirportAccess": airport_edges > 0,
            "callsignSpecificAdsBProof": False,
        },
    }


def shortest_path(
    graph: dict[str, dict[str, float]],
    start: str,
    target: str,
    route_start: tuple[float, float],
    route_end: tuple[float, float],
) -> tuple[list[str] | None, float]:
    if start not in graph or target not in graph:
        return None, float("inf")
    route_geometry_cache: dict[str, tuple[float, float]] = {}

    def allowed(node: str) -> bool:
        if node.startswith(AIRPORT_PREFIX):
            return True
        point = route_geometry_cache.get(node)
        if point is None:
            point = cell_center(node)
            route_geometry_cache[node] = point
        along = along_track_fraction(route_start, route_end, point)
        cross = cross_track_km(route_start, route_end, point)
        return ROUTE_CORRIDOR_ALONG_MIN <= along <= ROUTE_CORRIDOR_ALONG_MAX and cross <= MAX_ROUTE_CORRIDOR_CROSS_TRACK_KM

    target_point = route_end
    distances = {start: 0.0}
    previous: dict[str, str | None] = {start: None}
    queue = [(haversine(*route_start, *target_point), 0.0, start)]
    while queue:
        _, distance, current = heapq.heappop(queue)
        if distance != distances.get(current):
            continue
        if current == target:
            path = []
            while current is not None:
                path.append(current)
                current = previous[current]
            return list(reversed(path)), distance
        for neighbor, weight in graph[current].items():
            if not allowed(neighbor):
                continue
            candidate = distance + weight
            if candidate < distances.get(neighbor, float("inf")):
                distances[neighbor] = candidate
                previous[neighbor] = current
                if neighbor.startswith(AIRPORT_PREFIX):
                    heuristic = 0.0
                else:
                    point = route_geometry_cache.get(neighbor) or cell_center(neighbor)
                    route_geometry_cache[neighbor] = point
                    heuristic = haversine(*point, *target_point)
                heapq.heappush(queue, (candidate + heuristic, candidate, neighbor))
    return None, float("inf")


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians((lon2 - lon1 + 540.0) % 360.0 - 180.0)
    value = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(value)))


def initial_bearing(start: tuple[float, float], end: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(start[0]), math.radians(end[0])
    delta = math.radians((end[1] - start[1] + 540.0) % 360.0 - 180.0)
    return math.atan2(math.sin(delta) * math.cos(lat2), math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta))


def angular_distance(start: tuple[float, float], end: tuple[float, float]) -> float:
    return haversine(*start, *end) / EARTH_RADIUS_KM


def cross_track_km(start: tuple[float, float], end: tuple[float, float], point: tuple[float, float]) -> float:
    delta13 = angular_distance(start, point)
    bearing13 = initial_bearing(start, point)
    bearing12 = initial_bearing(start, end)
    value = math.sin(delta13) * math.sin(bearing13 - bearing12)
    return abs(math.asin(max(-1.0, min(1.0, value))) * EARTH_RADIUS_KM)


def along_track_fraction(start: tuple[float, float], end: tuple[float, float], point: tuple[float, float]) -> float:
    delta13 = angular_distance(start, point)
    bearing13 = initial_bearing(start, point)
    bearing12 = initial_bearing(start, end)
    along = math.atan2(math.sin(delta13) * math.cos(bearing13 - bearing12), math.cos(delta13))
    total = angular_distance(start, end)
    return along / total if total else 0.0


def cell_jump(left: str, right: str) -> tuple[int, int]:
    left_lat, left_lon = (int(value) for value in left.split(":"))
    right_lat, right_lon = (int(value) for value in right.split(":"))
    delta_lon = right_lon - left_lon
    if delta_lon > LON_CELL_COUNT // 2:
        delta_lon -= LON_CELL_COUNT
    elif delta_lon < -(LON_CELL_COUNT // 2):
        delta_lon += LON_CELL_COUNT
    return right_lat - left_lat, delta_lon


if __name__ == "__main__":
    raise SystemExit(main())
