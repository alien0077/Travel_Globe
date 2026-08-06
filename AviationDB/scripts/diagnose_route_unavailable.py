#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import heapq
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

from aviationdb.ifr_routing import DEFAULT_COST_CONFIG, DirectedAirgraph, haversine_nm  # noqa: E402
from select_pair_route_shape import airport_lookup  # noqa: E402


DEFAULT_AIRPORT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "airports-index.json"
DEFAULT_AIRGRAPH = ROOT / "shared" / "offline-packs" / "aviation" / "regions" / "global.airgraph.json"
DEFAULT_ROUTE_SHAPES = PROJECT / "data" / "releases" / "private" / "route-shapes" / "global.route-shapes.json.gz"
DEFAULT_OUTPUT = PROJECT / "data" / "releases" / "private" / "route-shapes" / "route-unavailable-diagnostics.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose routeUnavailable pairs from the directed route-shapes pack.")
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--airgraph", type=Path, default=DEFAULT_AIRGRAPH)
    parser.add_argument("--route-shapes", type=Path, default=DEFAULT_ROUTE_SHAPES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    airports = airport_lookup(args.airport_index)
    airgraph_pack = json.loads(args.airgraph.read_text(encoding="utf-8"))
    graph = DirectedAirgraph(airgraph_pack, DEFAULT_COST_CONFIG)
    route_shapes = read_json(args.route_shapes)
    skipped = route_shapes.get("skipped") or []

    diagnostics = []
    category_counts: Counter[str] = Counter()
    country_counts: Counter[str] = Counter()
    for row in skipped:
        route_id = row.get("id")
        if not isinstance(route_id, str) or "-" not in route_id:
            continue
        origin_iata, destination_iata = route_id.split("-", 1)
        origin = airports.get(origin_iata)
        destination = airports.get(destination_iata)
        diagnostic = diagnose_pair(graph, route_id, origin, destination, row)
        diagnostics.append(diagnostic)
        category_counts[diagnostic["category"]] += 1
        country_counts[f"{diagnostic.get('originCountry')} -> {diagnostic.get('destinationCountry')}"] += 1

    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourcePack": str(args.route_shapes),
        "summary": {
            "total": len(diagnostics),
            "categories": dict(category_counts),
            "topCountryPairs": country_counts.most_common(30),
        },
        "diagnostics": diagnostics,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"written": str(args.output), "summary": payload["summary"]}, ensure_ascii=False, indent=2))
    return 0


def read_json(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def diagnose_pair(
    graph: DirectedAirgraph,
    route_id: str,
    origin: dict[str, Any] | None,
    destination: dict[str, Any] | None,
    skipped_row: dict[str, Any],
) -> dict[str, Any]:
    if not origin or not destination:
        return {
            "id": route_id,
            "category": "missing_airport_metadata",
            "reason": skipped_row.get("reason"),
        }

    departure = graph.connectors(origin, mode="departure")
    arrival = graph.connectors(destination, mode="arrival")
    distance_nm = haversine_nm(origin["latitude"], origin["longitude"], destination["latitude"], destination["longitude"])
    raw_path = shortest_directed_path(graph, departure, arrival)
    reachable = {
        "reachable": raw_path is not None,
        "visitedNodes": raw_path.get("visitedNodes") if raw_path else 0,
        "matchedArrivalNode": raw_path.get("matchedArrivalNode") if raw_path else None,
        "edgeDepth": raw_path.get("edgeDepth") if raw_path else None,
    }
    detour_ratio = raw_path_detour_ratio(distance_nm, raw_path) if raw_path else None
    category = classify(distance_nm, departure, arrival, reachable, detour_ratio)

    return {
        "id": route_id,
        "originIata": route_id.split("-", 1)[0],
        "destinationIata": route_id.split("-", 1)[1],
        "originIcao": origin.get("icaoCode") or origin.get("ident"),
        "destinationIcao": destination.get("icaoCode") or destination.get("ident"),
        "originName": origin.get("name") or origin.get("airportName"),
        "destinationName": destination.get("name") or destination.get("airportName"),
        "originCountry": origin.get("country") or origin.get("countryName"),
        "destinationCountry": destination.get("country") or destination.get("countryName"),
        "distanceKm": round(distance_nm * 1.852, 1),
        "reason": skipped_row.get("reason"),
        "category": category,
        "connectorDiagnostics": {
            "departureConnectorCount": len(departure),
            "arrivalConnectorCount": len(arrival),
            "nearestDepartureConnectorNm": round(departure[0].distance_nm, 2) if departure else None,
            "nearestArrivalConnectorNm": round(arrival[0].distance_nm, 2) if arrival else None,
            "directedReachable": reachable["reachable"],
            "visitedNodes": reachable["visitedNodes"],
            "matchedArrivalNode": reachable.get("matchedArrivalNode"),
            "edgeDepth": reachable.get("edgeDepth"),
            "rawAirwayDistanceNm": round(raw_path["airwayDistanceNm"], 2) if raw_path else None,
            "rawConnectorDistanceNm": round(raw_path["connectorDistanceNm"], 2) if raw_path else None,
            "rawDetourRatio": round(detour_ratio, 3) if detour_ratio is not None else None,
            "rawPathPreview": raw_path.get("pathPreview") if raw_path else [],
        },
        "recommendedResolution": recommended_resolution(category),
    }


def shortest_directed_path(graph: DirectedAirgraph, departure: list[Any], arrival: list[Any]) -> dict[str, Any] | None:
    if not departure or not arrival:
        return None
    arrival_by_node = {connector.node_idx: connector for connector in arrival}
    queue: list[tuple[float, int, int]] = []
    best: dict[int, float] = {}
    previous: dict[int, int | None] = {}
    start_connector_by_node = {connector.node_idx: connector for connector in departure}
    visited_count = 0
    for connector in departure:
        best[connector.node_idx] = 0.0
        previous[connector.node_idx] = None
        heapq.heappush(queue, (0.0, connector.node_idx, 0))
    final_node = None
    final_depth = 0
    while queue:
        cost, node, depth = heapq.heappop(queue)
        if cost > best.get(node, float("inf")):
            continue
        visited_count += 1
        if depth > 0 and node in arrival_by_node:
            final_node = node
            final_depth = depth
            break
        for edge in graph.graph[node]:
            next_cost = cost + edge.distance_nm
            if next_cost < best.get(edge.to_idx, float("inf")):
                best[edge.to_idx] = next_cost
                previous[edge.to_idx] = node
                heapq.heappush(queue, (next_cost, edge.to_idx, depth + 1))
    if final_node is None:
        return None
    path = []
    cursor: int | None = final_node
    while cursor is not None:
        path.append(cursor)
        cursor = previous[cursor]
    path.reverse()
    start_connector = start_connector_by_node[path[0]]
    arrival_connector = arrival_by_node[final_node]
    return {
        "visitedNodes": visited_count,
        "matchedArrivalNode": final_node,
        "edgeDepth": final_depth,
        "airwayDistanceNm": best[final_node],
        "connectorDistanceNm": start_connector.distance_nm + arrival_connector.distance_nm,
        "pathPreview": [graph.points[index].ident for index in path[:12]],
    }


def raw_path_detour_ratio(distance_nm: float, raw_path: dict[str, Any] | None) -> float | None:
    if not raw_path or distance_nm <= 0:
        return None
    return (raw_path["airwayDistanceNm"] + raw_path["connectorDistanceNm"]) / distance_nm


def classify(distance_nm: float, departure: list[Any], arrival: list[Any], reachable: dict[str, Any], detour_ratio: float | None) -> str:
    if not departure:
        return "no_departure_connector"
    if not arrival:
        return "no_arrival_connector"
    if reachable["reachable"]:
        if detour_ratio is not None and detour_ratio <= 1.65:
            return "selector_constraints_rejected_recoverable"
        return "reachable_but_excessive_detour"
    if distance_nm <= 165:
        return "short_remote_pair_no_public_airway_path"
    return "public_airway_graph_gap"


def recommended_resolution(category: str) -> str:
    if category == "selector_constraints_rejected_recoverable":
        return "inspect scoring constraints; rebuild selected candidate only if edge validation remains directed and valid"
    if category == "reachable_but_excessive_detour":
        return "keep routeUnavailable or use observed ADS-B mapping; do not select the raw airway path because detour is excessive"
    if category == "short_remote_pair_no_public_airway_path":
        return "use explicit approximate_direct_fallback or observed ADS-B mapping; do not label as IFR airway"
    if category in {"no_departure_connector", "no_arrival_connector"}:
        return "add airport connector/source coverage or mark unavailable until a licensed source is available"
    if category == "public_airway_graph_gap":
        return "fill with observed ADS-B mapped route or another licensed public airway source; otherwise keep routeUnavailable"
    return "manual review"


if __name__ == "__main__":
    raise SystemExit(main())
