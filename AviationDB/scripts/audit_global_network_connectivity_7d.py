#!/usr/bin/env python3
"""Audit the assembled global corridor network without altering observed data.

This is a post-processing layer for the 0.25-degree assembled network.  It
keeps observed edges, relay-inferred links, and airport-access candidates
separate, then reports components and endpoint attachment evidence.  It never
creates airport-to-airport routes or invents missing middle geometry.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CELL_DEG = 0.25
AIRPORT_RADIUS_KM = 150.0
SPATIAL_BIN_CELLS = 8  # 2 degrees, used only as an endpoint lookup index.

Node = tuple[int, int]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit assembled global corridor connectivity.")
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--airports", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    _status(args.status, {"state": "running", "phase": "load"})

    network = _read_gzip(args.network)
    airport_pack = json.loads(args.airports.read_text(encoding="utf-8"))
    observed = list(network.get("observedEdges", []))
    relays = list(network.get("relayInferred", []))
    unresolved = list(network.get("unresolvedGaps", []))
    observed_adjacency, observed_nodes, edge_counts = _build_observed_graph(observed)
    relay_adjacency = _add_relays(observed_adjacency, relays)
    observed_components = _component_records(observed_adjacency, observed_nodes, observed)
    all_components = _component_records(relay_adjacency, observed_nodes, observed)
    _status(
        args.status,
        {
            "state": "running",
            "phase": "components",
            "observedNodes": len(observed_nodes),
            "observedComponents": len(observed_components),
            "componentsAfterRelay": len(all_components),
        },
    )

    airport_access = _airport_access(airport_pack.get("airports", []), observed_nodes)
    airport_adjacency = _airport_graph(relay_adjacency, airport_access)
    khh_nrt = _airport_pair_report(airport_access, airport_adjacency, "KHH", "NRT")
    summary = {
        "observedEdges": len(observed),
        "observedNodes": len(observed_nodes),
        "observedComponents": len(observed_components),
        "relayLinks": len(relays),
        "componentsAfterRelay": len(all_components),
        "unresolvedGaps": len(unresolved),
        "airportsWithObservedAccess": sum(bool(item["links"]) for item in airport_access),
        "airportsWithoutObservedAccess": sum(not bool(item["links"]) for item in airport_access),
        "airportAccessRadiusKm": AIRPORT_RADIUS_KM,
        "airportPairGeneration": False,
        "ifrExcluded": network.get("summary", {}).get("ifrUsed") is False,
        "observedGeometryUntouched": network.get("summary", {}).get("observedGeometryUntouched") is True,
        "inferredGeometryNotObserved": network.get("summary", {}).get("inferredGeometryNotObserved") is True,
    }
    qa = {
        "passed": all(
            [
                summary["observedEdges"] > 0,
                summary["relayLinks"] > 0,
                summary["airportPairGeneration"] is False,
                summary["ifrExcluded"],
                summary["observedGeometryUntouched"],
                summary["inferredGeometryNotObserved"],
            ]
        ),
        "checks": {
            "observedLayerPresent": summary["observedEdges"] > 0,
            "relayLayerPresent": summary["relayLinks"] > 0,
            "airportAccessSeparate": summary["airportPairGeneration"] is False,
            "ifrExcluded": summary["ifrExcluded"],
            "observedGeometryUntouched": summary["observedGeometryUntouched"],
            "inferredGeometrySeparated": summary["inferredGeometryNotObserved"],
        },
    }
    payload = {
        "schemaVersion": 1,
        "evidenceType": "assembled_global_network_connectivity_audit_v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "source": {"network": str(args.network), "airports": str(args.airports)},
        "summary": summary,
        "networkSummary": network.get("summary", {}),
        "observedComponents": observed_components,
        "componentsAfterRelay": all_components,
        "airportAccess": airport_access,
        "khhToNrt": khh_nrt,
        "unresolvedGapSummary": {
            "count": len(unresolved),
            "sample": unresolved[:500],
        },
        "qa": qa,
        "rules": {
            "airportAccessIsInferredOnly": True,
            "relayIsInferredOnly": True,
            "noAirportPairGeneration": True,
            "noLongStraightLineFill": True,
        },
    }
    _write_gzip(args.output_root / "global-connectivity-audit.json.gz", payload)
    (args.output_root / "global-connectivity-review.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "evidenceType": "global_connectivity_review",
                "generatedAt": payload["generatedAt"],
                "summary": summary,
                "khhToNrt": khh_nrt,
                "qa": qa,
                "limitations": [
                    "airport access links are endpoint hypotheses, not observed aircraft tracks",
                    "relay links do not create observed middle geometry",
                    "unresolved gaps remain explicit and are not silently filled",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _status(args.status, {"state": "complete", "phase": "written", "summary": summary, "qa": qa, "khhToNrt": khh_nrt})
    print(json.dumps({"state": "complete", "summary": summary, "qa": qa, "khhToNrt": khh_nrt}, ensure_ascii=False, indent=2))
    return 0 if qa["passed"] else 2


def _build_observed_graph(edges: list[dict[str, Any]]) -> tuple[dict[Node, set[Node]], set[Node], dict[Node, int]]:
    adjacency: dict[Node, set[Node]] = defaultdict(set)
    nodes: set[Node] = set()
    edge_counts: dict[Node, int] = defaultdict(int)
    for edge in edges:
        left, right = _nodes(edge)
        adjacency[left].add(right)
        adjacency[right].add(left)
        nodes.update((left, right))
        edge_counts[left] += 1
        edge_counts[right] += 1
    return adjacency, nodes, edge_counts


def _add_relays(adjacency: dict[Node, set[Node]], relays: list[dict[str, Any]]) -> dict[Node, set[Node]]:
    result: dict[Node, set[Node]] = defaultdict(set)
    for node, neighbors in adjacency.items():
        result[node].update(neighbors)
    for relay in relays:
        left, right = _nodes(relay)
        result[left].add(right)
        result[right].add(left)
    return result


def _component_records(adjacency: dict[Node, set[Node]], nodes: set[Node], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    component_by_node: dict[Node, int] = {}
    records: list[dict[str, Any]] = []
    for start in sorted(nodes):
        if start in component_by_node:
            continue
        component_id = len(records)
        queue = deque([start])
        component_nodes: list[Node] = []
        component_by_node[start] = component_id
        while queue:
            current = queue.popleft()
            component_nodes.append(current)
            for neighbor in adjacency.get(current, ()):
                if neighbor not in component_by_node:
                    component_by_node[neighbor] = component_id
                    queue.append(neighbor)
        records.append({"componentId": f"component-{component_id:05d}", "nodeCount": len(component_nodes), "edgeCount": 0, "regions": sorted({_region(node) for node in component_nodes if _region(node)})})
    for edge in edges:
        left, right = _nodes(edge)
        if left in component_by_node and component_by_node[left] == component_by_node.get(right):
            records[component_by_node[left]]["edgeCount"] += 1
    return records


def _airport_access(airports: list[dict[str, Any]], nodes: set[Node]) -> list[dict[str, Any]]:
    index: dict[tuple[int, int], list[Node]] = defaultdict(list)
    for node in nodes:
        index[(node[0] // SPATIAL_BIN_CELLS, node[1] // SPATIAL_BIN_CELLS)].append(node)
    output: list[dict[str, Any]] = []
    for airport in airports:
        code = str(airport.get("iataCode") or "").upper()
        if not code or airport.get("latitude") is None or airport.get("longitude") is None:
            continue
        lat = float(airport["latitude"])
        lon = float(airport["longitude"])
        airport_cell = _airport_cell(lat, lon)
        candidates: list[tuple[float, Node]] = []
        base = (airport_cell[0] // SPATIAL_BIN_CELLS, airport_cell[1] // SPATIAL_BIN_CELLS)
        for lat_bin in range(base[0] - 1, base[0] + 2):
            for lon_bin in range(base[1] - 1, base[1] + 2):
                for node in index.get((lat_bin, lon_bin), []):
                    distance = _cell_distance((lat, lon), node)
                    if distance <= AIRPORT_RADIUS_KM:
                        candidates.append((distance, node))
        candidates.sort(key=lambda item: (item[0], item[1]))
        output.append(
            {
                "iataCode": code,
                "latitude": lat,
                "longitude": lon,
                "links": [
                    {"node": _node(node), "distanceKm": round(distance, 3), "status": "airport_access_inferred"}
                    for distance, node in candidates[:3]
                ],
            }
        )
    return output


def _airport_graph(adjacency: dict[Node, set[Node]], airport_access: list[dict[str, Any]]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for left, neighbors in adjacency.items():
        left_key = _node_key(left)
        for right in neighbors:
            graph[left_key].add(_node_key(right))
    for airport in airport_access:
        for link in airport["links"]:
            airport_key = f"airport:{airport['iataCode']}"
            node_key = _node_key((link["node"]["latCell"], link["node"]["lonCell"]))
            graph[airport_key].add(node_key)
            graph[node_key].add(airport_key)
    return graph


def _airport_pair_report(access: list[dict[str, Any]], graph: dict[str, set[str]], origin: str, destination: str) -> dict[str, Any]:
    by_code = {item["iataCode"]: item for item in access}
    origin_item = by_code.get(origin, {"links": []})
    destination_item = by_code.get(destination, {"links": []})
    starts = {f"airport:{origin}"} if origin_item["links"] else set()
    targets = {f"airport:{destination}"} if destination_item["links"] else set()
    path = _bfs(starts, targets, graph)
    return {
        "origin": origin,
        "destination": destination,
        "originAccessLinks": origin_item["links"],
        "destinationAccessLinks": destination_item["links"],
        "pathFoundWithAirportAccess": path is not None,
        "pathNodeCount": len(path) if path else 0,
        "interpretation": "airport access is inferred endpoint evidence; it does not change observed geometry",
    }


def _bfs(starts: set[str], targets: set[str], graph: dict[str, set[str]]) -> list[str] | None:
    if not starts or not targets:
        return None
    queue = deque(starts)
    previous: dict[str, str | None] = {item: None for item in starts}
    found = next((item for item in starts if item in targets), None)
    while queue and found is None:
        current = queue.popleft()
        for neighbor in graph.get(current, ()):
            if neighbor in previous:
                continue
            previous[neighbor] = current
            if neighbor in targets:
                found = neighbor
                break
            queue.append(neighbor)
    if found is None:
        return None
    path: list[str] = []
    current: str | None = found
    while current is not None:
        path.append(current)
        current = previous[current]
    path.reverse()
    return path


def _airport_cell(lat: float, lon: float) -> Node:
    return math.floor((lat + 90.0) / CELL_DEG), math.floor((lon + 180.0) / CELL_DEG)


def _cell_distance(airport: tuple[float, float], node: Node) -> float:
    node_lat = node[0] * CELL_DEG - 90.0 + CELL_DEG / 2.0
    node_lon = node[1] * CELL_DEG - 180.0 + CELL_DEG / 2.0
    return _haversine(airport, (node_lat, node_lon))


def _haversine(left: tuple[float, float], right: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, left)
    lat2, lon2 = map(math.radians, right)
    dlon = ((lon2 - lon1 + math.pi) % (2 * math.pi)) - math.pi
    value = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(value)))


def _region(node: Node) -> str | None:
    lat = node[0] * CELL_DEG - 90.0 + CELL_DEG / 2.0
    lon = node[1] * CELL_DEG - 180.0 + CELL_DEG / 2.0
    for name, (lat_min, lat_max, lon_min, lon_max) in {
        "NorthAmerica": (10, 72, -170, -50),
        "SouthAmerica": (-56, 15, -82, -34),
        "Europe": (35, 72, -10, 45),
        "Africa": (-35, 37, -20, 52),
        "Asia": (5, 78, 45, 180),
        "Oceania": (-50, 0, 110, 180),
    }.items():
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return name
    return None


def _nodes(row: dict[str, Any]) -> tuple[Node, Node]:
    left, right = row["from"], row["to"]
    return (int(left["latCell"]), int(left["lonCell"])), (int(right["latCell"]), int(right["lonCell"]))


def _node(node: Node) -> dict[str, int]:
    return {"latCell": node[0], "lonCell": node[1]}


def _node_key(node: Node) -> str:
    return f"{node[0]}:{node[1]}"


def _read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _write_gzip(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def _status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({"updatedAt": datetime.now(UTC).isoformat(), **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
