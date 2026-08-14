#!/usr/bin/env python3
"""Validate KHH/NRT attachment against the assembled 0.25-degree network."""

from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import defaultdict, deque
from pathlib import Path

CELL_DEG = 0.25


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--airports", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with gzip.open(args.network, "rt", encoding="utf-8") as handle:
        network = json.load(handle)
    with args.airports.open(encoding="utf-8") as handle:
        airport_pack = json.load(handle)
    airports = {row.get("iataCode"): row for row in airport_pack.get("airports", [])}
    khh, nrt = airports.get("KHH"), airports.get("NRT")
    if not khh or not nrt:
        raise SystemExit("KHH or NRT missing from airport index")
    observed = network.get("observedEdges", [])
    relays = network.get("relayInferred", [])
    observed_adjacency: dict[tuple[int, int], list[tuple[tuple[int, int], str, bool]]] = defaultdict(list)
    adjacency: dict[tuple[int, int], list[tuple[tuple[int, int], str, bool]]] = defaultdict(list)
    node_support: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for edge in observed:
        a, b = _nodes(edge)
        observed_adjacency[a].append((b, edge["edgeKey"], False))
        observed_adjacency[b].append((a, edge["edgeKey"], False))
        adjacency[a].append((b, edge["edgeKey"], False))
        adjacency[b].append((a, edge["edgeKey"], False))
        node_support[a].append(edge)
        node_support[b].append(edge)
    for index, link in enumerate(relays):
        a, b = _nodes(link)
        key = f"relay-{index:06d}"
        adjacency[a].append((b, key, True))
        adjacency[b].append((a, key, True))

    khh_cell = _airport_cell(khh)
    nrt_cell = _airport_cell(nrt)
    khh_nodes = _nearby_nodes(khh, set(adjacency))
    nrt_nodes = _nearby_nodes(nrt, set(adjacency))
    observed_path = _bfs(khh_nodes, nrt_nodes, observed_adjacency)
    path = _bfs(khh_nodes, nrt_nodes, adjacency)
    report = {
        "schemaVersion": 1,
        "evidenceType": "khh_global_network_validation_v1",
        "networkSummary": network.get("summary", {}),
        "airports": {
            "KHH": {"latitude": khh["latitude"], "longitude": khh["longitude"], "cell": _node(khh_cell)},
            "NRT": {"latitude": nrt["latitude"], "longitude": nrt["longitude"], "cell": _node(nrt_cell)},
        },
        "join": {
            "khhNearbyObservedNodes": len(khh_nodes),
            "nrtNearbyObservedNodes": len(nrt_nodes),
            "khhNearestKm": min((_cell_distance(khh, node) for node in khh_nodes), default=None),
            "nrtNearestKm": min((_cell_distance(nrt, node) for node in nrt_nodes), default=None),
        },
        "khhToNrt": {
            "pathFound": path is not None,
            "observedOnlyPathFound": observed_path is not None,
            "edgeCount": len(path["edges"]) if path else 0,
            "relayEdgeCount": sum(row["isRelay"] for row in path["edges"]) if path else 0,
            "observedOnlyEdgeCount": len(observed_path["edges"]) if observed_path else 0,
            "nodes": [_node(node) for node in path["nodes"]] if path else [],
            "edges": path["edges"] if path else [],
        },
        "interpretation": "KHH/NRT are validation endpoints; path geometry remains observed edges plus separately marked relay links.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": "complete", "pathFound": report["khhToNrt"]["pathFound"], "join": report["join"]}, ensure_ascii=False))
    return 0


def _airport_cell(airport: dict) -> tuple[int, int]:
    return math.floor((airport["latitude"] + 90) / CELL_DEG), math.floor((airport["longitude"] + 180) / CELL_DEG)


def _nearby_nodes(airport: dict, nodes: set[tuple[int, int]]) -> set[tuple[int, int]]:
    return {node for node in nodes if _cell_distance(airport, node) <= 150.0}


def _cell_distance(airport: dict, node: tuple[int, int]) -> float:
    lat = node[0] * CELL_DEG - 90 + CELL_DEG / 2
    lon = node[1] * CELL_DEG - 180 + CELL_DEG / 2
    return _haversine((airport["latitude"], airport["longitude"]), (lat, lon))


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat = lat2 - lat1
    dlon = math.radians(((b[1] - a[1] + 180) % 360) - 180)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(value)))


def _nodes(row: dict) -> tuple[tuple[int, int], tuple[int, int]]:
    return (int(row["from"]["latCell"]), int(row["from"]["lonCell"])), (int(row["to"]["latCell"]), int(row["to"]["lonCell"]))


def _node(node: tuple[int, int]) -> dict[str, int]:
    return {"latCell": node[0], "lonCell": node[1]}


def _bfs(starts: set[tuple[int, int]], targets: set[tuple[int, int]], adjacency: dict) -> dict | None:
    if not starts or not targets:
        return None
    queue = deque(starts)
    previous: dict[tuple[int, int], tuple[tuple[int, int] | None, str | None, bool]] = {node: (None, None, False) for node in starts}
    found = next((node for node in starts if node in targets), None)
    while queue and found is None:
        current = queue.popleft()
        for neighbor, edge_key, is_relay in adjacency[current]:
            if neighbor in previous:
                continue
            previous[neighbor] = (current, edge_key, is_relay)
            if neighbor in targets:
                found = neighbor
                break
            queue.append(neighbor)
    if found is None:
        return None
    nodes = []
    edges = []
    current = found
    while current is not None:
        nodes.append(current)
        prior, edge_key, is_relay = previous[current]
        if prior is not None:
            edges.append({"edgeKey": edge_key, "isRelay": is_relay})
        current = prior
    nodes.reverse()
    edges.reverse()
    return {"nodes": nodes, "edges": edges}


if __name__ == "__main__":
    raise SystemExit(main())
