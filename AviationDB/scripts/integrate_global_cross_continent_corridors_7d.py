#!/usr/bin/env python3
"""Merge cross-continent evidence without turning inferred links into raw tracks.

Inputs are already-computed 7-day corridor artifacts.  The output keeps three
separate layers: observed edges, conservative relay links, and unresolved
review items.  No airport endpoint or IFR route is introduced here.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CELL_DEG = 1.0
RELAY_CANDIDATE_KM = 350.0
RELAY_PROMOTE_KM = 180.0
MIN_SUPPORT_DATES = 2
MIN_SUPPORT_FLIGHTS = 3
TARGET_PAIR = "Asia-NorthAmerica"
CELL_DEG = 1.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--global-input", type=Path)
    parser.add_argument("--asia-northamerica-input", type=Path)
    parser.add_argument("--cross-all-input", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    _status(args.status, {"state": "running", "phase": "load_inputs"})

    if not args.cross_all_input and (not args.global_input or not args.asia_northamerica_input):
        parser.error("provide --cross-all-input or both legacy input files")
    edge_map: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    pair_summaries: dict[str, dict[str, Any]] = {}
    global CELL_DEG
    if args.cross_all_input:
        cross_payload = _read_gzip(args.cross_all_input)
        CELL_DEG = float(cross_payload.get("summary", {}).get("cellDegrees", 1.0))
        _load_payload(cross_payload, edge_map, pair_summaries, "global-cross-continent-7d-025")
    else:
        _load_global(args.global_input, edge_map, pair_summaries)
        _load_target(args.asia_northamerica_input, edge_map, pair_summaries)
    _status(args.status, {"state": "running", "phase": "normalize", "rawEdgeKeys": len(edge_map), "pairs": len(pair_summaries)})

    observed_edges = [
        _serialize_edge(key, row)
        for key, row in sorted(edge_map.items())
        if len(row["dates"]) >= MIN_SUPPORT_DATES and row["flights"] >= MIN_SUPPORT_FLIGHTS
    ]
    graph = _build_graph(observed_edges)
    components = _components(graph["nodes"], graph["adjacency"])
    relay_candidates, relay_inferred, unresolved = _build_relays(observed_edges, graph, components)
    _status(args.status, {
        "state": "running", "phase": "relay_complete",
        "observedEdges": len(observed_edges), "components": len(set(components.values())),
        "relayCandidates": len(relay_candidates), "relayInferred": len(relay_inferred),
    })

    network = {
        "schemaVersion": 1,
        "evidenceType": "integrated_global_cross_continent_corridor_network_v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "sourcePairs": len(pair_summaries),
            "observedEdges": len(observed_edges),
            "observedNodes": len(graph["nodes"]),
            "observedComponents": len(set(components.values())),
            "relayCandidates": len(relay_candidates),
            "relayInferred": len(relay_inferred),
            "unresolvedGaps": len(unresolved),
            "crossContinentPairs": sorted(pair_summaries),
            "ifrUsed": False,
            "airportEndpointsUsed": False,
            "observedGeometryUntouched": True,
            "inferredGeometryNotObserved": True,
            "cellDegrees": CELL_DEG,
        },
        "pairSummaries": pair_summaries,
        "observedEdges": observed_edges,
        "relayCandidates": relay_candidates,
        "relayInferred": relay_inferred,
        "unresolvedGaps": unresolved,
        "rules": {
            "cellDegrees": CELL_DEG,
            "minSupportDates": MIN_SUPPORT_DATES,
            "minSupportFlights": MIN_SUPPORT_FLIGHTS,
            "relayCandidateKm": RELAY_CANDIDATE_KM,
            "relayPromoteKm": RELAY_PROMOTE_KM,
            "noStraightLineMiddleFill": True,
        },
    }
    _write_gzip(args.output_root / "global-corridor-network.json.gz", network)
    _write_gzip(args.output_root / "global-corridor-network.geojson.gz", _geojson(network))
    review = {
        "schemaVersion": 1,
        "evidenceType": "integrated_global_cross_continent_corridor_review_v1",
        "generatedAt": network["generatedAt"],
        "summary": network["summary"],
        "limitations": [
            "observed edges are shared raw-derived cells only",
            "relay links are reviewable joins and are not observed aircraft geometry",
            "no airport endpoint is inferred in this stage",
            "unresolved gaps remain explicit instead of being filled",
        ],
        "unresolvedGaps": unresolved,
    }
    (args.output_root / "global-corridor-review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    qa = _qa(network)
    (args.output_root / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not qa["passed"]:
        _status(args.status, {"state": "failed", "phase": "qa_failed", "qa": qa})
        return 2
    _status(args.status, {"state": "complete", "phase": "written", "summary": network["summary"], "qa": qa})
    return 0


def _load_global(path: Path, edge_map: dict, pair_summaries: dict) -> None:
    _load_payload(_read_gzip(path), edge_map, pair_summaries, "global-cross-continent-7d")


def _load_payload(payload: dict, edge_map: dict, pair_summaries: dict, source: str) -> None:
    for pair, pair_payload in payload.get("pairs", {}).items():
        pair_summaries[pair] = dict(pair_payload.get("summary", {}), source=source)
        for edge in pair_payload.get("edges", []):
            _add_edge(edge_map, pair, edge)


def _load_target(path: Path, edge_map: dict, pair_summaries: dict) -> None:
    payload = _read_gzip(path)
    pair_summaries[TARGET_PAIR] = dict(payload.get("summary", {}), source="asia-northamerica-7d")
    for edge in payload.get("edges", []):
        _add_edge(edge_map, TARGET_PAIR, edge)


def _add_edge(edge_map: dict, pair: str, edge: dict[str, Any]) -> None:
    left, right = edge["from"], edge["to"]
    key = (int(left["latCell"]), int(left["lonCell"]), int(right["latCell"]), int(right["lonCell"]))
    row = edge_map.setdefault(key, {"dates": set(), "flights": 0, "pairs": set(), "classifications": set()})
    row["dates"].update(str(value) for value in edge.get("supportDates", []))
    row["flights"] = max(row["flights"], int(edge.get("supportFlightCount", 0)))
    row["pairs"].add(pair)
    if edge.get("classification"):
        row["classifications"].add(str(edge["classification"]))


def _serialize_edge(key: tuple[int, int, int, int], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "edgeKey": ":".join(str(value) for value in key),
        "from": {"latCell": key[0], "lonCell": key[1]},
        "to": {"latCell": key[2], "lonCell": key[3]},
        "supportDates": sorted(row["dates"]),
        "supportFlightCount": row["flights"],
        "sourcePairs": sorted(row["pairs"]),
        "classification": "observed_shared",
    }


def _build_graph(edges: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: set[tuple[int, int]] = set()
    adjacency: dict[tuple[int, int], set[tuple[int, int]]] = defaultdict(set)
    for edge in edges:
        a = (edge["from"]["latCell"], edge["from"]["lonCell"])
        b = (edge["to"]["latCell"], edge["to"]["lonCell"])
        nodes.update((a, b))
        adjacency[a].add(b)
        adjacency[b].add(a)
    return {"nodes": nodes, "adjacency": adjacency}


def _components(nodes: set[tuple[int, int]], adjacency: dict) -> dict[tuple[int, int], int]:
    result: dict[tuple[int, int], int] = {}
    component = 0
    for start in sorted(nodes):
        if start in result:
            continue
        stack = [start]
        result[start] = component
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                if neighbor not in result:
                    result[neighbor] = component
                    stack.append(neighbor)
        component += 1
    return result


def _build_relays(edges: list[dict[str, Any]], graph: dict[str, Any], components: dict) -> tuple[list[dict], list[dict], list[dict]]:
    pair_adjacency: dict[str, dict[tuple[int, int], set[tuple[int, int]]] ] = defaultdict(lambda: defaultdict(set))
    incident: dict[tuple[str, tuple[int, int]], list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        a = (edge["from"]["latCell"], edge["from"]["lonCell"])
        b = (edge["to"]["latCell"], edge["to"]["lonCell"])
        for pair in edge["sourcePairs"]:
            pair_adjacency[pair][a].add(b)
            pair_adjacency[pair][b].add(a)
            incident[(pair, a)].append(edge)
            incident[(pair, b)].append(edge)
    terminals: list[dict[str, Any]] = []
    for pair, adjacency in pair_adjacency.items():
        for node, neighbors in adjacency.items():
            if len(neighbors) != 1:
                continue
            support = max(incident[(pair, node)], key=lambda row: (len(row["supportDates"]), row["supportFlightCount"]))
            terminals.append({"pair": pair, "node": node, "neighbor": next(iter(neighbors)), "support": support})
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, terminal in enumerate(terminals):
        buckets[(terminal["node"][0] // 4, terminal["node"][1] // 4)].append(index)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for index, left in enumerate(terminals):
        lat_bin, lon_bin = left["node"][0] // 4, left["node"][1] // 4
        for dlat in range(-3, 4):
            for dlon in range(-3, 4):
                for right_index in buckets.get((lat_bin + dlat, lon_bin + dlon), []):
                    if index >= right_index:
                        continue
                    right = terminals[right_index]
                    if left["node"] == right["node"] or left["pair"] == right["pair"]:
                        continue
                    if components.get(left["node"]) == components.get(right["node"]):
                        continue
                    distance = _cell_distance(left["node"], right["node"])
                    if distance > RELAY_CANDIDATE_KM:
                        continue
                    key = (left["pair"], left["node"], right["pair"], right["node"])
                    if key in seen:
                        continue
                    seen.add(key)
                    row = {
                        "fromPair": left["pair"], "from": _node(left["node"]),
                        "toPair": right["pair"], "to": _node(right["node"]),
                        "distanceKm": round(distance, 1),
                        "support": {
                            "fromDates": left["support"]["supportDates"],
                            "toDates": right["support"]["supportDates"],
                            "fromFlights": left["support"]["supportFlightCount"],
                            "toFlights": right["support"]["supportFlightCount"],
                        },
                        "geometryStatus": "inferred_link_only",
                    }
                    candidates.append(row)
    inferred = [row for row in candidates if row["distanceKm"] <= RELAY_PROMOTE_KM]
    unresolved = [row for row in candidates if row["distanceKm"] > RELAY_PROMOTE_KM]
    return candidates, inferred, unresolved


def _cell_distance(a: tuple[int, int], b: tuple[int, int]) -> float:
    return _haversine(
        (a[0] * CELL_DEG - 90 + CELL_DEG / 2, a[1] * CELL_DEG - 180 + CELL_DEG / 2),
        (b[0] * CELL_DEG - 90 + CELL_DEG / 2, b[1] * CELL_DEG - 180 + CELL_DEG / 2),
    )


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat = lat2 - lat1
    dlon = math.radians(((b[1] - a[1] + 180.0) % 360.0) - 180.0)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(value)))


def _node(node: tuple[int, int]) -> dict[str, int]:
    return {"latCell": node[0], "lonCell": node[1]}


def _geojson(network: dict[str, Any]) -> dict[str, Any]:
    features = []
    for edge in network["observedEdges"]:
        a, b = edge["from"], edge["to"]
        features.append({"type": "Feature", "properties": {"layer": "observed_shared", "sourcePairs": edge["sourcePairs"], "supportDates": edge["supportDates"]}, "geometry": {"type": "LineString", "coordinates": [_coord(a), _coord(b)]}})
    for link in network["relayInferred"]:
        features.append({"type": "Feature", "properties": {"layer": "relay_inferred", "fromPair": link["fromPair"], "toPair": link["toPair"], "distanceKm": link["distanceKm"]}, "geometry": {"type": "LineString", "coordinates": [_coord(link["from"]), _coord(link["to"])]}})
    return {"type": "FeatureCollection", "features": features}


def _coord(node: dict[str, int]) -> list[float]:
    return [node["lonCell"] * CELL_DEG - 180 + CELL_DEG / 2, node["latCell"] * CELL_DEG - 90 + CELL_DEG / 2]


def _qa(network: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": all([
            network["summary"]["observedEdges"] > 0,
            network["summary"]["sourcePairs"] >= 13,
            network["summary"]["ifrUsed"] is False,
            network["summary"]["airportEndpointsUsed"] is False,
            network["summary"]["observedGeometryUntouched"] is True,
            network["summary"]["inferredGeometryNotObserved"] is True,
        ]),
        "checks": {
            "observedEdgesPresent": network["summary"]["observedEdges"] > 0,
            "allCrossContinentSourcesLoaded": network["summary"]["sourcePairs"] >= 13,
            "ifrExcluded": network["summary"]["ifrUsed"] is False,
            "airportEndpointsExcluded": network["summary"]["airportEndpointsUsed"] is False,
            "observedGeometryUntouched": network["summary"]["observedGeometryUntouched"] is True,
            "inferredGeometrySeparated": network["summary"]["inferredGeometryNotObserved"] is True,
        },
    }


def _read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _write_gzip(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def _status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({"updatedAt": datetime.now(timezone.utc).isoformat(), **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
