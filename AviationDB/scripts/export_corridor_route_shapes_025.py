#!/usr/bin/env python3
"""Build airport-pair route shapes from the 0.25-degree corridor network.

The corridor network is a shared observed-edge graph with explicitly tagged
inferred relays and airport-access links.  This exporter turns that graph into
runtime-consumable airport-pair shapes.  It never labels a relay or airport
connector as observed geometry.
"""

from __future__ import annotations

import argparse
import gzip
import heapq
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
DEFAULT_NETWORK = ROOT / "AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d-025-repaired-2026-08-01-v16/global-corridor-network.json.gz"
DEFAULT_AUDIT = ROOT / "AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d-025-repaired-2026-08-01-v16/connectivity/global-connectivity-audit.json.gz"
DEFAULT_AIRPORTS = ROOT / "shared/offline-packs/core-global/airports-index.json"
DEFAULT_RUNTIME = ROOT / "shared/offline-packs/route-shapes/global.route-shapes.runtime.json"
DEFAULT_OUTPUT = ROOT / "shared/offline-packs/route-shapes/global.route-shapes.runtime-corridor-025.json"
CELL_DEG = 0.25
EARTH_RADIUS_KM = 6371.0088
CORRIDOR_METHOD = "corridor_025_graph"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--airports", type=Path, default=DEFAULT_AIRPORTS)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--status", type=Path)
    parser.add_argument("--max-routes", type=int)
    parser.add_argument("--route", action="append", dest="routes", help="Build only the named route; repeatable for focused QA.")
    args = parser.parse_args()

    status = args.status or args.output.with_suffix(args.output.suffix + ".status.json")
    write_status(status, {"state": "running", "phase": "load"})
    network = read_gzip(args.network)
    audit = read_gzip(args.audit)
    airports = airport_lookup(args.airports)
    runtime = json.loads(args.runtime.read_text(encoding="utf-8"))
    route_ids = sorted((runtime.get("routes") or {}).keys())
    if args.routes:
        route_ids = sorted(set(args.routes) & set(route_ids))
    if args.max_routes is not None:
        route_ids = route_ids[: args.max_routes]

    graph, access = build_graph(network, audit)
    write_status(status, {"state": "running", "phase": "routing", "routeCount": len(route_ids), "graphNodes": len(graph)})
    routes: dict[str, dict[str, Any]] = {}
    counters: Counter[str] = Counter()
    failed: list[dict[str, Any]] = []
    for index, route_id in enumerate(route_ids, 1):
        try:
            origin, destination = route_id.split("-", 1)
        except ValueError:
            counters["invalid_route_id"] += 1
            continue
        path = shortest_path(graph, access, origin, destination)
        if path is None or origin not in airports or destination not in airports:
            counters["no_corridor_path"] += 1
        else:
            route, kinds = compact_corridor_route(route_id, path, airports[origin], airports[destination])
            routes[route_id] = route
            counters["corridor_routes"] += 1
            counters["corridor_observed_only"] += int(kinds == {"observed"})
            counters["corridor_with_relay"] += int("relay_inferred" in kinds)
            counters["corridor_with_airport_access"] += int("airport_access_inferred" in kinds)
        if index % 100 == 0:
            write_status(status, {"state": "running", "phase": "routing", "routeCount": len(route_ids), "processed": index, "routesBuilt": len(routes), "counters": dict(counters)})

    payload = {
        "schemaVersion": 1,
        "evidenceType": "global_corridor_route_shapes_025_v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "source": {
            "network": str(args.network),
            "connectivityAudit": str(args.audit),
            "airportIndex": str(args.airports),
            "ifrUsed": False,
        },
        "method": {
            "cellDegrees": CELL_DEG,
            "pathSelection": "Dijkstra over observed corridor edges plus explicitly tagged relay and airport-access edges",
            "observedGeometryUntouched": True,
            "inferredGeometryTagged": True,
        },
        "summary": {
            "routeIdsConsidered": len(route_ids),
            **dict(counters),
            "routeCount": len(routes),
            "airportAccessIsInferred": True,
            "relayGeometryIsInferred": True,
        },
        "routes": routes,
        "failed": failed,
    }
    write_json(args.output, payload)
    write_status(status, {"state": "complete", "phase": "written", "output": str(args.output), "summary": payload["summary"]})
    print(json.dumps({"state": "complete", "output": str(args.output), "summary": payload["summary"]}, ensure_ascii=False, indent=2))
    return 0


def read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def airport_lookup(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = {}
    for airport in payload.get("airports", []):
        code = str(airport.get("iataCode") or "").upper()
        if code and airport.get("latitude") is not None and airport.get("longitude") is not None:
            result[code] = airport
    return result


def cell_node(row: dict[str, Any]) -> tuple[int, int]:
    return int(row["latCell"]), int(row["lonCell"])


def airport_node(code: str) -> str:
    return f"airport:{code}"


def build_graph(network: dict[str, Any], audit: dict[str, Any]) -> tuple[dict[Any, list[tuple[Any, float, str]]], dict[str, list[tuple[Any, float, str]]]]:
    graph: dict[Any, list[tuple[Any, float, str]]] = {}

    def add(left: Any, right: Any, distance: float, kind: str) -> None:
        graph.setdefault(left, []).append((right, max(float(distance), 0.001), kind))
        graph.setdefault(right, []).append((left, max(float(distance), 0.001), kind))

    for edge in network.get("observedEdges", []):
        left, right = cell_node(edge["from"]), cell_node(edge["to"])
        add(left, right, cell_distance(left, right), "observed")
    for link in network.get("relayInferred", []):
        left, right = cell_node(link["from"]), cell_node(link["to"])
        add(left, right, link.get("distanceKm") or cell_distance(left, right), "relay_inferred")

    access: dict[str, list[tuple[Any, float, str]]] = {}
    for item in audit.get("airportAccess", []):
        code = str(item.get("iataCode") or "").upper()
        if not code:
            continue
        for link in item.get("links", []):
            node = cell_node(link["node"])
            distance = link.get("distanceKm") or 0.001
            entry = (node, float(distance), "airport_access_inferred")
            access.setdefault(code, []).append(entry)
            add(airport_node(code), node, distance, "airport_access_inferred")
    return graph, access


def shortest_path(graph: dict[Any, list[tuple[Any, float, str]]], access: dict[str, list[tuple[Any, float, str]]], origin: str, destination: str) -> tuple[list[Any], list[str]] | None:
    start, target = airport_node(origin), airport_node(destination)
    if start not in graph or target not in graph:
        return None
    # The graph contains hundreds of thousands of cells.  A one-sided search
    # repeatedly expands an entire intercontinental component; bidirectional
    # Dijkstra keeps the work near the two airport access regions.
    forward_targets = [(node, distance) for node, distance, _ in access.get(destination, [])]
    backward_targets = [(node, distance) for node, distance, _ in access.get(origin, [])]
    forward_queue: list[tuple[float, float, int, Any]] = [(0.0, 0.0, 0, start)]
    backward_queue: list[tuple[float, float, int, Any]] = [(0.0, 0.0, 0, target)]
    forward_dist: dict[Any, float] = {start: 0.0}
    backward_dist: dict[Any, float] = {target: 0.0}
    forward_prev: dict[Any, tuple[Any, str]] = {}
    backward_next: dict[Any, tuple[Any, str]] = {}
    serial = 0
    best = float("inf")
    meet: Any | None = None

    def expand(
        queue: list[tuple[float, float, int, Any]],
        own: dict[Any, float],
        other: dict[Any, float],
        links: dict[Any, tuple[Any, str]],
        heuristic_targets: list[tuple[Any, float]],
    ) -> None:
        nonlocal serial, best, meet
        _, distance, _, current = heapq.heappop(queue)
        if distance != own.get(current):
            return
        if distance > best:
            return
        for neighbor, edge_distance, kind in graph.get(current, []):
            candidate = distance + edge_distance
            if candidate >= own.get(neighbor, float("inf")):
                continue
            own[neighbor] = candidate
            links[neighbor] = (current, kind)
            serial += 1
            heapq.heappush(queue, (candidate + corridor_heuristic(neighbor, heuristic_targets), candidate, serial, neighbor))
            if neighbor in other and candidate + other[neighbor] < best:
                best = candidate + other[neighbor]
                meet = neighbor

    while forward_queue and backward_queue:
        if forward_queue[0][0] <= backward_queue[0][0]:
            expand(forward_queue, forward_dist, backward_dist, forward_prev, forward_targets)
        else:
            expand(backward_queue, backward_dist, forward_dist, backward_next, backward_targets)
        if meet is not None and forward_queue[0][0] + backward_queue[0][0] >= best:
            break
    if meet is None:
        return None

    left_nodes = [meet]
    left_kinds: list[str] = []
    current = meet
    while current != start:
        prior, kind = forward_prev[current]
        left_nodes.append(prior)
        left_kinds.append(kind)
        current = prior
    left_nodes.reverse()
    left_kinds.reverse()

    right_nodes: list[Any] = []
    right_kinds: list[str] = []
    current = meet
    while current != target:
        next_node, kind = backward_next[current]
        right_nodes.append(next_node)
        right_kinds.append(kind)
        current = next_node
    return left_nodes + right_nodes, left_kinds + right_kinds


def corridor_heuristic(node: Any, targets: list[tuple[Any, float]]) -> float:
    if not isinstance(node, tuple) or not targets:
        return 0.0
    return min(cell_distance(node, target) + access_distance for target, access_distance in targets)


def compact_corridor_route(route_id: str, path: tuple[list[Any], list[str]], origin: dict[str, Any], destination: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    nodes, kinds = path
    points = [[str(origin["iataCode"]).upper(), float(origin["latitude"]), float(origin["longitude"]), "AIRPORT"]]
    for node in nodes:
        if not isinstance(node, tuple):
            continue
        lat, lon = cell_center(node)
        points.append([f"C025_{node[0]}_{node[1]}", lat, lon, "CORRIDOR_CELL"])
    points.append([[str(destination["iataCode"]).upper()][0], float(destination["latitude"]), float(destination["longitude"]), "AIRPORT"])
    points = dedupe_points(points)
    distance_km = sum(haversine(a[1], a[2], b[1], b[2]) for a, b in zip(points, points[1:]))
    warnings = ["0.25-degree global corridor path; not a callsign-specific ADS-B flight trace."]
    if "relay_inferred" in kinds:
        warnings.append("Path includes inferred shared-corridor relay links.")
    if "airport_access_inferred" in kinds:
        warnings.append("Airport-to-corridor connector is inferred from the airport-access layer.")
    if kinds and set(kinds) == {"observed", "airport_access_inferred"}:
        warnings.append("Middle corridor edges are observed, while endpoint connectors remain inferred.")
    return {
        "m": CORRIDOR_METHOD,
        "s": 0,
        "d": round(distance_km * 1000),
        "w": warnings,
        "p": points,
    }, set(kinds)


def dedupe_points(points: list[list[Any]]) -> list[list[Any]]:
    result = []
    for point in points:
        if result and point[1] == result[-1][1] and point[2] == result[-1][2]:
            continue
        result.append(point)
    return result


def cell_center(node: tuple[int, int]) -> tuple[float, float]:
    return node[0] * CELL_DEG - 90.0 + CELL_DEG / 2.0, node[1] * CELL_DEG - 180.0 + CELL_DEG / 2.0


def cell_distance(left: tuple[int, int], right: tuple[int, int]) -> float:
    a, b = cell_center(left), cell_center(right)
    return haversine(a[0], a[1], b[0], b[1])


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    left_lat, right_lat = math.radians(lat1), math.radians(lat2)
    dlat = right_lat - left_lat
    dlon = math.radians(((lon2 - lon1 + 540.0) % 360.0) - 180.0)
    value = math.sin(dlat / 2) ** 2 + math.cos(left_lat) * math.cos(right_lat) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_KM * 2 * math.asin(min(1.0, math.sqrt(value)))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temp.replace(path)


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({"updatedAt": datetime.now(UTC).isoformat(), **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
