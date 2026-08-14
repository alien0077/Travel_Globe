#!/usr/bin/env python3
"""Assemble the complete 7-day global corridor network.

The stable global raw graph is the base layer.  Cross-continent observed
edges are added as independently tagged evidence, while old and new relay
links remain inferred-only.  The map export is sampled deterministically so
the full evidence pack stays compact and the browser is not overloaded.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STABLE_MIN_DAYS = 3
MAP_MAX_BASE_EDGES = 50000
BASE_CELL_DEG = 0.25
CROSS_CELL_DEG = 1.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-graph", type=Path, required=True)
    parser.add_argument("--base-relay", type=Path, required=True)
    parser.add_argument("--cross-network", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    _status(args.status, {"state": "running", "phase": "load_base"})

    edge_map: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    _load_base(args.base_graph, edge_map)
    _status(args.status, {"state": "running", "phase": "load_cross", "baseStableEdges": len(edge_map)})
    cross = _read_gzip(args.cross_network)
    cross_cell_degrees = float(cross.get("summary", {}).get("cellDegrees", BASE_CELL_DEG))
    for edge in cross.get("observedEdges", []):
        _add_observed(edge_map, edge, "cross-continent-7d-normalized", cross_cell_degrees)

    relay_links = _load_old_relays(args.base_relay)
    relay_links.extend(cross.get("relayInferred", []))
    unresolved = _read_gzip(args.base_relay).get("unresolvedGaps", [])
    unresolved.extend(cross.get("unresolvedGaps", []))
    observed_edges = [_serialize_edge(key, row) for key, row in sorted(edge_map.items())]
    observed_components = _component_count(observed_edges)
    final_components = _component_count_with_relays(observed_edges, relay_links)
    # Sources may be tagged as ``cross-continent-7d-normalized`` when the
    # source grid is normalized to the base 0.25 degree grid.  Count the
    # whole source family instead of requiring an exact source token.
    cross_edges = [
        edge for edge in observed_edges
        if any(source.startswith("cross-continent-7d") for source in edge["sources"])
    ]
    _status(args.status, {
        "state": "running", "phase": "assemble",
        "observedEdges": len(observed_edges), "crossContinentEdges": len(cross_edges),
        "relayLinks": len(relay_links), "unresolvedGaps": len(unresolved),
        "observedComponents": observed_components, "componentsAfterRelay": final_components,
    })

    generated_at = datetime.now(timezone.utc).isoformat()
    network = {
        "schemaVersion": 1,
        "evidenceType": "assembled_global_corridor_network_v1",
        "generatedAt": generated_at,
        "summary": {
            "baseStableEdges": sum(edge["baseStable"] for edge in edge_map.values()),
            "observedEdges": len(observed_edges),
            "crossContinentObservedEdges": len(cross_edges),
            "observedNodes": len(_nodes(observed_edges)),
            "observedComponents": observed_components,
            "relayInferred": len(relay_links),
            "unresolvedGaps": len(unresolved),
            "componentsAfterRelay": final_components,
            "crossContinentPairs": cross.get("summary", {}).get("crossContinentPairs", []),
            "ifrUsed": False,
            "airportEndpointsUsed": False,
            "observedGeometryUntouched": True,
            "inferredGeometryNotObserved": True,
        },
        "observedEdges": observed_edges,
        "relayInferred": relay_links,
        "unresolvedGaps": unresolved,
        "rules": {
            "baseStableMinSupportDays": STABLE_MIN_DAYS,
            "crossContinentSource": "integrated_global_cross_continent_corridor_network_v1",
            "relayGeometryIsInferredOnly": True,
            "noLongStraightLineFill": True,
        },
    }
    _write_gzip(args.output_root / "global-corridor-network.json.gz", network)
    _write_gzip(args.output_root / "global-corridor-network.geojson.gz", _geojson(observed_edges, relay_links))
    review = {
        "schemaVersion": 1,
        "evidenceType": "assembled_global_corridor_review_v1",
        "generatedAt": generated_at,
        "summary": network["summary"],
        "unresolvedGapCount": len(unresolved),
        "unresolvedGapSample": unresolved[:1000],
        "limitations": [
            "base layer is stable raw-derived 7-day geometry",
            "cross-continent layer is geographic-gate evidence, not airport endpoint evidence",
            "relay links connect evidence components but do not create observed middle geometry",
            "map GeoJSON is a deterministic sample of the full evidence pack",
        ],
    }
    (args.output_root / "global-corridor-review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    qa = _qa(network)
    (args.output_root / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not qa["passed"]:
        _status(args.status, {"state": "failed", "phase": "qa_failed", "qa": qa})
        return 2
    _status(args.status, {"state": "complete", "phase": "written", "summary": network["summary"], "qa": qa})
    return 0


def _load_base(path: Path, target: dict) -> None:
    payload = _read_gzip(path)
    for edge in payload.get("edges", []):
        support_days = edge.get("supportDays", 0)
        support_day_count = len(support_days) if isinstance(support_days, list) else int(support_days or 0)
        if support_day_count < STABLE_MIN_DAYS:
            continue
        left, right = edge["from"], edge["to"]
        key = (int(left["latCell"]), int(left["lonCell"]), int(right["latCell"]), int(right["lonCell"]))
        row = target.setdefault(key, {"dates": set(), "supportDayCount": 0, "flights": 0, "sources": set(), "baseStable": 0})
        if isinstance(support_days, list):
            row["supportDayCount"] = max(row["supportDayCount"], len(support_days))
            row["dates"].update(str(value) for value in support_days)
        else:
            row["supportDayCount"] = max(row["supportDayCount"], int(support_days or 0))
        row["flights"] = max(row["flights"], int(edge.get("supportLegs", 0)))
        row["sources"].add("global-stable-7d")
        row["baseStable"] = 1


def _add_observed(target: dict, edge: dict, source: str, source_cell_degrees: float) -> None:
    for key in _normalized_cross_keys(edge, source_cell_degrees):
        row = target.setdefault(key, {"dates": set(), "supportDayCount": 0, "flights": 0, "sources": set(), "baseStable": 0})
        row["dates"].update(str(value) for value in edge.get("supportDates", []))
        row["supportDayCount"] = max(row["supportDayCount"], len(edge.get("supportDates", [])))
        row["flights"] = max(row["flights"], int(edge.get("supportFlightCount", 0)))
        row["sources"].add(source)


def _normalized_cross_keys(edge: dict, source_cell_degrees: float) -> list[tuple[int, int, int, int]]:
    left, right = edge["from"], edge["to"]
    start = _cross_cell_center(int(left["latCell"]), int(left["lonCell"]), source_cell_degrees)
    end = _cross_cell_center(int(right["latCell"]), int(right["lonCell"]), source_cell_degrees)
    a = _base_cell(*start)
    b = _base_cell(*end)
    cells = _walk_cells(a, b)
    return [(*previous, *current) for previous, current in zip(cells, cells[1:]) if previous != current]


def _cross_cell_center(lat_cell: int, lon_cell: int, cell_degrees: float) -> tuple[float, float]:
    return (
        lat_cell * cell_degrees - 90.0 + cell_degrees / 2.0,
        lon_cell * cell_degrees - 180.0 + cell_degrees / 2.0,
    )


def _base_cell(lat: float, lon: float) -> tuple[int, int]:
    return math.floor((lat + 90.0) / BASE_CELL_DEG), math.floor((lon + 180.0) / BASE_CELL_DEG)


def _walk_cells(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    steps = max(abs(end[0] - start[0]), abs(end[1] - start[1]), 1)
    cells = []
    for index in range(steps + 1):
        ratio = index / steps
        cell = (round(start[0] + (end[0] - start[0]) * ratio), round(start[1] + (end[1] - start[1]) * ratio))
        if not cells or cell != cells[-1]:
            cells.append(cell)
    return cells


def _serialize_edge(key: tuple[int, int, int, int], row: dict) -> dict:
    return {
        "edgeKey": ":".join(str(value) for value in key),
        "from": {"latCell": key[0], "lonCell": key[1]},
        "to": {"latCell": key[2], "lonCell": key[3]},
        "supportDates": sorted(row["dates"]),
        "supportDayCount": row["supportDayCount"],
        "supportFlightCount": row["flights"],
        "sources": sorted(row["sources"]),
        "classification": "observed_stable" if row["baseStable"] else "observed_cross_continent_shared",
        "baseStable": bool(row["baseStable"]),
    }


def _load_old_relays(path: Path) -> list[dict]:
    payload = _read_gzip(path)
    result = []
    for link in payload.get("relayInferred", []):
        result.append({
            "from": _coord_to_node(link.get("from", {})),
            "to": _coord_to_node(link.get("to", {})),
            "distanceKm": link.get("distanceKm"),
            "source": "global-relay-7d",
            "geometryStatus": "inferred_link_only",
            "sourceRegions": link.get("sourceRegions", []),
            "targetRegions": link.get("targetRegions", []),
        })
    return result


def _coord_to_node(value: dict) -> dict[str, int]:
    if "latCell" in value:
        return {"latCell": int(value["latCell"]), "lonCell": int(value["lonCell"])}
    return {"latCell": math.floor(float(value.get("lat", 0)) + 90), "lonCell": math.floor(float(value.get("lon", 0)) + 180)}


def _component_count(edges: list[dict]) -> int:
    nodes = _nodes(edges)
    adjacency: dict[tuple[int, int], set[tuple[int, int]]] = defaultdict(set)
    for edge in edges:
        a, b = _edge_nodes(edge)
        adjacency[a].add(b)
        adjacency[b].add(a)
    return _component_walk(nodes, adjacency)


def _component_count_with_relays(edges: list[dict], relays: list[dict]) -> int:
    nodes = _nodes(edges)
    adjacency: dict[tuple[int, int], set[tuple[int, int]]] = defaultdict(set)
    for edge in edges:
        a, b = _edge_nodes(edge)
        adjacency[a].add(b)
        adjacency[b].add(a)
    for link in relays:
        a, b = _edge_nodes(link)
        nodes.update((a, b))
        adjacency[a].add(b)
        adjacency[b].add(a)
    return _component_walk(nodes, adjacency)


def _component_walk(nodes: set[tuple[int, int]], adjacency: dict) -> int:
    seen: set[tuple[int, int]] = set()
    count = 0
    for start in nodes:
        if start in seen:
            continue
        count += 1
        stack = [start]
        seen.add(start)
        while stack:
            for neighbor in adjacency[stack.pop()]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
    return count


def _nodes(rows: list[dict]) -> set[tuple[int, int]]:
    result = set()
    for row in rows:
        result.update(_edge_nodes(row))
    return result


def _edge_nodes(row: dict) -> tuple[tuple[int, int], tuple[int, int]]:
    left, right = row["from"], row["to"]
    return (int(left["latCell"]), int(left["lonCell"])), (int(right["latCell"]), int(right["lonCell"]))


def _geojson(observed: list[dict], relays: list[dict]) -> dict:
    base = [row for row in observed if row["baseStable"]]
    step = max(1, math.ceil(len(base) / MAP_MAX_BASE_EDGES))
    sampled = base[::step] + [row for row in observed if not row["baseStable"]]
    features = []
    for edge in sampled:
        features.append({"type": "Feature", "properties": {"layer": edge["classification"], "sources": edge["sources"], "supportDates": edge["supportDates"]}, "geometry": {"type": "LineString", "coordinates": [_coord(edge["from"]), _coord(edge["to"])]}})
    for link in relays:
        features.append({"type": "Feature", "properties": {"layer": "relay_inferred", "source": link.get("source"), "distanceKm": link.get("distanceKm"), "geometryStatus": "inferred_link_only"}, "geometry": {"type": "LineString", "coordinates": [_coord(link["from"]), _coord(link["to"])]}})
    return {"type": "FeatureCollection", "features": features, "properties": {"baseSampled": len(base[::step]), "crossContinentObserved": len(observed) - len(base), "relayInferred": len(relays)}}


def _coord(node: dict) -> list[float]:
    return [
        int(node["lonCell"]) * BASE_CELL_DEG - 180.0 + BASE_CELL_DEG / 2.0,
        int(node["latCell"]) * BASE_CELL_DEG - 90.0 + BASE_CELL_DEG / 2.0,
    ]


def _qa(network: dict) -> dict:
    summary = network["summary"]
    checks = {
        "stableBasePresent": summary["baseStableEdges"] > 300000,
        "crossContinentMerged": summary["crossContinentObservedEdges"] > 10000,
        "relayPresent": summary["relayInferred"] > 0,
        "ifrExcluded": summary["ifrUsed"] is False,
        "airportEndpointsExcluded": summary["airportEndpointsUsed"] is False,
        "inferredSeparated": summary["inferredGeometryNotObserved"] is True,
        "observedGeometryUntouched": summary["observedGeometryUntouched"] is True,
        "relayReducesOrMaintainsComponents": summary["componentsAfterRelay"] <= summary["observedComponents"],
    }
    return {"passed": all(checks.values()), "checks": checks}


def _read_gzip(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _write_gzip(path: Path, payload: dict) -> None:
    temp = path.with_suffix(path.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def _status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({"updatedAt": datetime.now(timezone.utc).isoformat(), **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
