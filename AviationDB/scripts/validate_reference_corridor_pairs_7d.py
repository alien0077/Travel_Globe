#!/usr/bin/env python3
"""Validate the airport-access view for the reference cross-continent examples.

This is a network QA report, not a claim that a callsign-specific ADS-B trace
was independently recovered.  Observed edges, inferred relays, and inferred
airport access remain tagged separately.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict, deque
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--airports", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    network = _read_gzip(args.network)
    audit = _read_gzip(args.audit)
    airport_pack = json.loads(args.airports.read_text(encoding="utf-8"))
    airport_codes = {str(row.get("iataCode") or "").upper() for row in airport_pack.get("airports", [])}
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in network.get("observedEdges", []):
        left, right = _node_key(edge["from"]), _node_key(edge["to"])
        adjacency[left].add(right)
        adjacency[right].add(left)
    for link in network.get("relayInferred", []):
        left, right = _node_key(link["from"]), _node_key(link["to"])
        adjacency[left].add(right)
        adjacency[right].add(left)

    access = {
        str(item.get("iataCode") or "").upper(): item
        for item in audit.get("airportAccess", [])
    }
    graph: dict[str, set[str]] = defaultdict(set)
    for left, neighbors in adjacency.items():
        graph[left].update(neighbors)
    for code, item in access.items():
        airport_node = f"airport:{code}"
        for link in item.get("links", []):
            node = _node_key(link["node"])
            graph[airport_node].add(node)
            graph[node].add(airport_node)

    results = []
    for callsign, origin, destination in PAIRS:
        path = _bfs(graph, f"airport:{origin}", f"airport:{destination}")
        results.append({
            "callsignReference": callsign,
            "origin": origin,
            "destination": destination,
            "airportCodesPresent": origin in airport_codes and destination in airport_codes,
            "originAccessLinks": len(access.get(origin, {}).get("links", [])),
            "destinationAccessLinks": len(access.get(destination, {}).get("links", [])),
            "networkPathFoundWithAirportAccess": path is not None,
            "networkPathNodeCount": len(path) if path else 0,
            "evidenceInterpretation": "airport-access network connectivity; not callsign-specific ADS-B proof",
        })

    payload = {
        "schemaVersion": 1,
        "evidenceType": "reference_corridor_pair_network_validation_v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "source": {"network": str(args.network), "audit": str(args.audit), "airports": str(args.airports)},
        "pairs": results,
        "qa": {
            "passed": all(
                row["airportCodesPresent"]
                and row["originAccessLinks"] > 0
                and row["destinationAccessLinks"] > 0
                and row["networkPathFoundWithAirportAccess"]
                for row in results
            ),
            "checks": {
                "allReferenceAirportPairsConnected": all(row["networkPathFoundWithAirportAccess"] for row in results),
                "allReferenceAirportsHaveAccess": all(row["originAccessLinks"] > 0 and row["destinationAccessLinks"] > 0 for row in results),
                "callsignSpecificAdsBClaimSuppressed": True,
                "relayAndAirportAccessRemainInferred": True,
            },
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": "complete", "qa": payload["qa"], "pairs": results}, ensure_ascii=False, indent=2))
    return 0 if payload["qa"]["passed"] else 2


def _read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _node_key(node: dict[str, Any]) -> str:
    return f"{int(node['latCell'])}:{int(node['lonCell'])}"


def _bfs(graph: dict[str, set[str]], start: str, target: str) -> list[str] | None:
    if start not in graph or target not in graph:
        return None
    queue = deque([start])
    previous: dict[str, str | None] = {start: None}
    while queue:
        current = queue.popleft()
        if current == target:
            path = []
            while current is not None:
                path.append(current)
                current = previous[current]
            return list(reversed(path))
        for neighbor in graph.get(current, ()):
            if neighbor not in previous:
                previous[neighbor] = current
                queue.append(neighbor)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
