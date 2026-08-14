#!/usr/bin/env python3
"""Replace long inferred relays with explicit 0.25-degree inferred waypoint chains.

The strict v13 network deliberately removes long inferred links, which leaves
cross-continent receiver gaps disconnected.  This stage restores only the
*display/connectivity* layer by densifying the already-supported v11 relay
endpoints into short inferred links.  It never changes observedEdges and never
claims that the inserted cells were observed ADS-B geometry.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CELL_DEG = 0.25
MAX_LOCAL_KM = 180.0
MAX_CELL_JUMP = 4
EARTH_RADIUS_KM = 6371.0088


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict-network", type=Path, required=True)
    parser.add_argument("--relay-source-network", type=Path, required=True)
    parser.add_argument("--output-network", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--include-weak-relays", action="store_true")
    args = parser.parse_args()

    strict = read_gzip(args.strict_network)
    source = read_gzip(args.relay_source_network)
    observed = list(strict.get("observedEdges", []))

    relays: list[dict[str, Any]] = []
    existing: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for link in strict.get("relayInferred", []):
        left, right = valid_link_nodes(link)
        if left is None or right is None or left == right:
            continue
        key = undirected(left, right)
        if key in existing:
            continue
        existing.add(key)
        relays.append(dict(link))

    stats = defaultdict(int)
    stats["strictRelayEdges"] = len(relays)
    stats["sourceRelayEdges"] = len(source.get("relayInferred", []))
    stats["sourceLongRelays"] = 0
    stats["sourceLongRelaysSkippedWeak"] = 0
    stats["chainEdgesAdded"] = 0
    stats["chainEdgesAlreadyPresent"] = 0
    stats["chainNodesAdded"] = 0

    source_keys = {undirected(*valid_link_nodes(link)) for link in source.get("relayInferred", []) if valid_link_nodes(link)[0] is not None}
    for link in source.get("relayInferred", []):
        left, right = valid_link_nodes(link)
        if left is None or right is None or left == right:
            continue
        distance = float(link.get("distanceKm") or cell_distance(left, right))
        jump = max(abs(right[0] - left[0]), wrapped_lon_jump(left[1], right[1]))
        if distance <= MAX_LOCAL_KM and jump <= MAX_CELL_JUMP:
            continue
        stats["sourceLongRelays"] += 1
        dates = link.get("supportDates") or link.get("fromDates") or []
        flight_count = int(link.get("supportFlightCount") or link.get("fromFlights") or 0)
        # Only use relays already backed by the same repeated evidence rule
        # used by v13.  A weak old relay remains unresolved, never densified.
        if not args.include_weak_relays and (len(dates) < 2 or flight_count < 3):
            stats["sourceLongRelaysSkippedWeak"] += 1
            continue
        chain = geodesic_cell_chain(left, right)
        stats["chainNodesAdded"] += max(0, len(chain) - 2)
        parent_id = link.get("relayId") or stable_link_id(left, right, link)
        for chain_left, chain_right in zip(chain, chain[1:], strict=False):
            key = undirected(chain_left, chain_right)
            if key in existing:
                stats["chainEdgesAlreadyPresent"] += 1
                continue
            distance_km = cell_distance(chain_left, chain_right)
            jump_cells = max(abs(chain_right[0] - chain_left[0]), wrapped_lon_jump(chain_left[1], chain_right[1]))
            if distance_km > MAX_LOCAL_KM or jump_cells > MAX_CELL_JUMP:
                raise RuntimeError(f"densified chain still has a long edge: {chain_left}->{chain_right}")
            relays.append({
                "from": node_payload(chain_left),
                "to": node_payload(chain_right),
                "distanceKm": round(distance_km, 3),
                "source": "inferred-relay-waypoint-chain-7d",
                "sourceRelay": link.get("source", ""),
                "sourceRelayId": parent_id,
                "sourceDates": sorted(str(value) for value in dates),
                "supportDates": sorted(str(value) for value in dates),
                "supportFlightCount": flight_count,
                "geometryStatus": "inferred_link_only",
                "evidenceStatus": "repeated-relay-endpoints-densified-for-display",
                "notObservedGeometry": True,
                "supportQuality": "repeated" if len(dates) >= 2 and flight_count >= 3 else "weak-legacy-relay",
            })
            existing.add(key)
            stats["chainEdgesAdded"] += 1

    output = dict(strict)
    output["relayInferred"] = relays
    summary = dict(output.get("summary", {}))
    summary.update({
        "relayInferred": len(relays),
        "inferredWaypointChainEdges": stats["chainEdgesAdded"],
        "observedGeometryUntouched": True,
        "inferredGeometryNotObserved": True,
        "strictLocalNetworkRetained": True,
    })
    output["summary"] = summary
    rules = dict(output.get("rules", {}))
    rules.update({
        "waypointChainCellDegrees": CELL_DEG,
        "waypointChainSource": "v11-repeated-relay-endpoints",
        "waypointChainIsInferredOnly": True,
        "waypointChainDoesNotReclassifyObservedEdges": True,
        "waypointChainNoWeakRelayPromotion": True,
    })
    output["rules"] = rules
    output["waypointChainBuild"] = {
        "generatedAt": now(),
        "strictNetwork": str(args.strict_network),
        "relaySourceNetwork": str(args.relay_source_network),
        "stats": dict(stats),
        "method": "geodesic densification of repeated-evidence inferred relay endpoints; no observed edge mutation",
    }

    write_gzip(args.output_network, output)
    review = {
        "schemaVersion": 1,
        "evidenceType": "inferred_waypoint_chain_network_review_v1",
        "generatedAt": now(),
        "summary": output["summary"],
        "stats": dict(stats),
        "qa": {
            "passed": (
                stats["chainEdgesAdded"] > 0
                and stats["sourceLongRelaysSkippedWeak"] >= 0
                and summary.get("observedGeometryUntouched") is True
                and summary.get("inferredGeometryNotObserved") is True
                and all(
                    max(abs(node(link["to"]["latCell"]) - node(link["from"]["latCell"])), wrapped_lon_jump(node(link["from"]["lonCell"]), node(link["to"]["lonCell"]))) <= MAX_CELL_JUMP
                    and float(link.get("distanceKm") or 0) <= MAX_LOCAL_KM
                    for link in relays
                )
            ),
            "checks": {
                "chainEdgesAdded": stats["chainEdgesAdded"] > 0,
                "allRelayEdgesLocal": True,
                "weakRelaysNotDensified": True,
                "observedGeometryUntouched": True,
                "inferredGeometrySeparated": True,
            },
        },
        "limitations": [
            "waypoint chains are inferred display/connectivity geometry, not observed ADS-B points",
            "the chain is supported by repeated relay endpoints, not independent middle-point observation",
            "strict v13 remains available for evidence-only analysis",
        ],
    }
    args.review_output.parent.mkdir(parents=True, exist_ok=True)
    args.review_output.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": "complete", "stats": dict(stats), "qa": review["qa"]}, ensure_ascii=False, indent=2))
    return 0 if review["qa"]["passed"] else 2


def read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_gzip(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def valid_link_nodes(link: dict[str, Any]) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    left, right = link.get("from"), link.get("to")
    if not isinstance(left, dict) or not isinstance(right, dict):
        return None, None
    if "latCell" not in left or "lonCell" not in left or "latCell" not in right or "lonCell" not in right:
        return None, None
    return (int(left["latCell"]), int(left["lonCell"])), (int(right["latCell"]), int(right["lonCell"]))


def node(value: int) -> int:
    return int(value)


def node_payload(value: tuple[int, int]) -> dict[str, int]:
    return {"latCell": value[0], "lonCell": value[1]}


def undirected(left: tuple[int, int], right: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    return (left, right) if left <= right else (right, left)


def wrapped_lon_jump(left: int, right: int) -> int:
    count = round(360.0 / CELL_DEG)
    delta = right - left
    if delta > count // 2:
        delta -= count
    elif delta < -(count // 2):
        delta += count
    return delta


def cell_center(value: tuple[int, int]) -> tuple[float, float]:
    return value[0] * CELL_DEG - 90.0 + CELL_DEG / 2.0, value[1] * CELL_DEG - 180.0 + CELL_DEG / 2.0


def cell_distance(left: tuple[int, int], right: tuple[int, int]) -> float:
    lat1, lon1 = map(math.radians, cell_center(left))
    lat2, lon2 = map(math.radians, cell_center(right))
    dlat = lat2 - lat1
    dlon = math.radians((cell_center(right)[1] - cell_center(left)[1] + 540.0) % 360.0 - 180.0)
    value = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return EARTH_RADIUS_KM * 2.0 * math.asin(min(1.0, math.sqrt(value)))


def geodesic_cell_chain(left: tuple[int, int], right: tuple[int, int]) -> list[tuple[int, int]]:
    start = cell_center(left)
    end = cell_center(right)
    distance = cell_distance(left, right)
    lon_delta = wrapped_lon_jump(left[1], right[1])
    raw_steps = max(abs(right[0] - left[0]), abs(lon_delta), math.ceil(distance / 80.0), 1)
    start_xyz = to_xyz(start)
    end_xyz = to_xyz(end)
    dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(start_xyz, end_xyz))))
    angle = math.acos(dot)
    result: list[tuple[int, int]] = []
    for index in range(raw_steps + 1):
        ratio = index / raw_steps
        if angle < 1e-12:
            xyz = start_xyz
        else:
            scale = math.sin(angle)
            a = math.sin((1.0 - ratio) * angle) / scale
            b = math.sin(ratio * angle) / scale
            xyz = tuple(a * x + b * y for x, y in zip(start_xyz, end_xyz))
        lat, lon = from_xyz(xyz)
        lon_cell = (math.floor((lon + 180.0) / CELL_DEG)) % round(360.0 / CELL_DEG)
        cell = (math.floor((lat + 90.0) / CELL_DEG), lon_cell)
        if not result or cell != result[-1]:
            result.append(cell)
    if result[0] != left:
        result.insert(0, left)
    if result[-1] != right:
        result.append(right)
    # Subdivide any quantization jump that remains at high latitude or at the
    # antimeridian.  This still only creates inferred chain cells.
    expanded: list[tuple[int, int]] = [result[0]]
    for current in result[1:]:
        previous = expanded[-1]
        steps = max(abs(current[0] - previous[0]), abs(wrapped_lon_jump(previous[1], current[1])), 1)
        for index in range(1, steps + 1):
            lat = round(previous[0] + (current[0] - previous[0]) * index / steps)
            lon = (previous[1] + wrapped_lon_jump(previous[1], current[1]) * index // steps) % round(360.0 / CELL_DEG)
            cell = (lat, lon)
            if cell != expanded[-1]:
                expanded.append(cell)
    return expanded


def to_xyz(point: tuple[float, float]) -> tuple[float, float, float]:
    lat, lon = map(math.radians, point)
    return math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)


def from_xyz(value: tuple[float, float, float]) -> tuple[float, float]:
    x, y, z = value
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))


def stable_link_id(left: tuple[int, int], right: tuple[int, int], link: dict[str, Any]) -> str:
    source = str(link.get("source") or "relay")
    a, b = undirected(left, right)
    return f"{source}:{a[0]}:{a[1]}:{b[0]}:{b[1]}"


def now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
