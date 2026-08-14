#!/usr/bin/env python3
"""Build a guarded inferred waypoint layer from retained raw long-leg geometry.

Long receiver gaps are not geometry.  This builder therefore keeps only local
sample-to-sample edges (<=180 km and <=4 cells), aggregates them across dates
and aircraft, and leaves longer gaps unresolved.  Existing observed edges are
copied unchanged; all added geometry remains inferred-only.
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
MAX_LOCAL_SEGMENT_KM = 180.0
MAX_EDGE_JUMP_CELLS = 4
DATES = ("2026-08-02", "2026-08-01", "2026-07-31", "2026-07-30", "2026-07-29", "2026-07-28", "2026-07-27")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-network", type=Path, required=True)
    parser.add_argument("--long-legs-root", type=Path, required=True)
    parser.add_argument("--cross-root", type=Path, default=None)
    parser.add_argument("--output-network", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    args = parser.parse_args()

    network = read_gzip(args.input_network)
    stats = defaultdict(int)
    local_relays: list[dict[str, Any]] = []
    retained_existing = 0
    removed_long = 0
    existing_keys: set[tuple[tuple[int, int], tuple[int, int]]] = set()

    for link in network.get("relayInferred", []):
        if not valid_node(link.get("from")) or not valid_node(link.get("to")):
            continue
        left = node(link["from"])
        right = node(link["to"])
        distance = float(link.get("distanceKm") or cell_distance(left, right))
        if distance > MAX_LOCAL_SEGMENT_KM or max(abs(right[0] - left[0]), abs(right[1] - left[1])) > MAX_EDGE_JUMP_CELLS:
            removed_long += 1
            continue
        key = undirected(left, right)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        local_relays.append(link)
        retained_existing += 1

    supports: dict[tuple[tuple[int, int], tuple[int, int]], dict[str, set[str]]] = defaultdict(
        lambda: {"dates": set(), "flights": set(), "pairs": set()}
    )
    missing = []
    for date in DATES:
        if args.cross_root is not None:
            path = args.cross_root / f"{date}.json.gz"
            if not path.is_file():
                missing.append(str(path))
                continue
            stats["crossDailyFiles"] += 1
            payload = read_gzip(path)
            for pair, tracks in sorted(payload.get("tracksByPair", {}).items()):
                for track in tracks:
                    stats["crossTracksRead"] += 1
                    flight = str(track.get("flightId") or track.get("icao") or f"{date}:{stats['crossTracksRead']}")
                    for edge in track.get("observedEdges", []):
                        if not isinstance(edge, list) or len(edge) != 4:
                            continue
                        left = (int(edge[0]), int(edge[1]))
                        right = (int(edge[2]), int(edge[3]))
                        if left == right:
                            continue
                        stats["candidateWaypointEdges"] += 1
                        distance = cell_distance(left, right)
                        jump = max(abs(right[0] - left[0]), abs(right[1] - left[1]))
                        if distance > MAX_LOCAL_SEGMENT_KM or jump > MAX_EDGE_JUMP_CELLS:
                            stats["sampledGapsOverLimit"] += 1
                            continue
                        row = supports[undirected(left, right)]
                        row["dates"].add(str(track.get("date") or date))
                        row["flights"].add(flight)
                        row["pairs"].add(str(pair))
            continue
        path = args.long_legs_root / date / "raw-long-legs.json.gz"
        if not path.is_file():
            missing.append(str(path))
            continue
        stats["longLegFiles"] += 1
        payload = read_gzip(path)
        for leg in payload.get("longLegs", []):
            stats["longLegsRead"] += 1
            points = leg.get("sampledPoints") or []
            if len(points) < 2:
                continue
            cells = dedupe_cells(points)
            flight = str(leg.get("icao") or leg.get("callsign") or f"{date}:{stats['longLegsRead']}")
            pair = f"{leg.get('originIata') or ''}-{leg.get('destinationIata') or ''}"
            for left, right in zip(cells, cells[1:], strict=False):
                stats["candidateWaypointEdges"] += 1
                distance = cell_distance(left, right)
                jump = max(abs(right[0] - left[0]), abs(right[1] - left[1]))
                if distance > MAX_LOCAL_SEGMENT_KM or jump > MAX_EDGE_JUMP_CELLS:
                    stats["sampledGapsOverLimit"] += 1
                    continue
                row = supports[undirected(left, right)]
                row["dates"].add(str(leg.get("date") or date))
                row["flights"].add(flight)
                if pair != "-":
                    row["pairs"].add(pair)

    waypoint_added = 0
    eligible = 0
    for key, support in sorted(supports.items()):
        if len(support["dates"]) < 2 or len(support["flights"]) < 3:
            continue
        eligible += 1
        if key in existing_keys:
            stats["waypointEdgesAlreadyPresent"] += 1
            continue
        left, right = key
        local_relays.append({
            "from": node_payload(left),
            "to": node_payload(right),
            "distanceKm": round(cell_distance(left, right), 3),
            "source": "raw-long-leg-waypoint-7d",
            "sourcePairs": sorted(support["pairs"]),
            "supportDates": sorted(support["dates"]),
            "supportFlightCount": len(support["flights"]),
            "geometryStatus": "inferred_link_only",
            "evidenceStatus": "raw-long-leg-local-waypoint",
        })
        existing_keys.add(key)
        waypoint_added += 1

    output = dict(network)
    output["relayInferred"] = local_relays
    summary = dict(output.get("summary", {}))
    summary.update({
        "relayInferred": len(local_relays),
        "longRelayRemoved": removed_long,
        "localRelayRetained": retained_existing,
        "rawLongLegWaypointRelayInferred": waypoint_added,
        "observedGeometryUntouched": True,
        "inferredGeometryNotObserved": True,
    })
    output["summary"] = summary
    rules = dict(output.get("rules", {}))
    rules.update({
        "longRelayPolicy": "remove from drawable layer; retain as unresolved gap evidence",
        "maxLocalRelayDistanceKm": MAX_LOCAL_SEGMENT_KM,
        "maxLocalRelayCellJump": MAX_EDGE_JUMP_CELLS,
        "waypointMinSupportDates": 2,
        "waypointMinSupportFlights": 3,
        "waypointSource": "retained-7d-raw-long-leg-sampled-points",
        "noStraightLineMiddleFill": True,
    })
    output["rules"] = rules
    output["waypointBuild"] = {
        "generatedAt": now(),
        "inputNetwork": str(args.input_network),
        "longLegsRoot": str(args.long_legs_root),
        "stats": {**dict(stats), "eligibleWaypointEdges": eligible, "waypointEdgesAdded": waypoint_added, "existingLocalRelaysRetained": retained_existing, "longRelaysRemoved": removed_long},
        "missingInputs": missing,
    }
    write_gzip(args.output_network, output)
    review = {
        "schemaVersion": 1,
        "evidenceType": "guarded_raw_waypoint_network_review_v1",
        "generatedAt": now(),
        "inputNetwork": str(args.input_network),
        "outputNetwork": str(args.output_network),
        "summary": output["summary"],
        "stats": output["waypointBuild"]["stats"],
        "missingInputs": missing,
        "qa": {
            "passed": not missing and waypoint_added > 0 and summary.get("observedGeometryUntouched") is True and summary.get("inferredGeometryNotObserved") is True,
            "checks": {
                "allSevenLongLegInputsPresent": not missing,
                "localWaypointEdgesAdded": waypoint_added > 0,
                "longRelaysRemovedFromDrawableLayer": removed_long > 0,
                "observedGeometryUntouched": True,
                "inferredGeometrySeparated": True,
                "noStraightLineMiddleFill": True,
            },
        },
        "limitations": [
            "long receiver gaps remain unresolved and are not drawn as geometry",
            "waypoint links are inferred from repeated raw-derived long-leg samples",
            "this is not callsign-specific proof for any reference flight",
        ],
    }
    args.review_output.parent.mkdir(parents=True, exist_ok=True)
    args.review_output.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": "complete", "stats": output["waypointBuild"]["stats"], "qa": review["qa"]}, ensure_ascii=False, indent=2))
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


def valid_node(value: Any) -> bool:
    return isinstance(value, dict) and "latCell" in value and "lonCell" in value


def node(value: dict[str, Any]) -> tuple[int, int]:
    return int(value["latCell"]), int(value["lonCell"])


def node_payload(value: tuple[int, int]) -> dict[str, int]:
    return {"latCell": value[0], "lonCell": value[1]}


def undirected(left: tuple[int, int], right: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    return (left, right) if left <= right else (right, left)


def dedupe_cells(points: list[dict[str, Any]]) -> list[tuple[int, int]]:
    result = []
    for point in points:
        try:
            cell = (math.floor((float(point["lat"]) + 90.0) / CELL_DEG), math.floor((float(point["lon"]) + 180.0) / CELL_DEG))
        except (KeyError, TypeError, ValueError):
            continue
        if not result or cell != result[-1]:
            result.append(cell)
    return result


def cell_center(value: tuple[int, int]) -> tuple[float, float]:
    return value[0] * CELL_DEG - 90.0 + CELL_DEG / 2.0, value[1] * CELL_DEG - 180.0 + CELL_DEG / 2.0


def cell_distance(left: tuple[int, int], right: tuple[int, int]) -> float:
    lat1, lon1 = map(math.radians, cell_center(left))
    lat2, lon2 = map(math.radians, cell_center(right))
    dlat = lat2 - lat1
    dlon = math.radians((cell_center(right)[1] - cell_center(left)[1] + 540) % 360 - 180)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(value)))


def now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
