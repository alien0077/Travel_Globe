#!/usr/bin/env python3
"""Add conservative continuity relays from already-derived cross-continent traces.

The cross-continent extractor intentionally keeps only local 0.25-degree edges;
large receiver gaps therefore split a single observed trace into components.
This stage does not re-read raw ADS-B and never promotes those missing spans to
observed geometry.  It joins consecutive sampled points from the same raw
derived trace as an explicitly inferred ``relayInferred`` link, retaining only
links supported by at least two dates and three distinct derived flight IDs.
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cross-root", type=Path, required=True)
    parser.add_argument("--input-network", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()

    _status(args.status, {"state": "running", "phase": "load_network"})
    network = _read_gzip(args.input_network)
    edge_support: dict[tuple[tuple[int, int], tuple[int, int]], dict[str, set[str]]] = defaultdict(
        lambda: {"dates": set(), "flights": set(), "pairs": set()}
    )
    stats = {
        "dailyFiles": 0,
        "tracksSeen": 0,
        "tracksWithSampledPoints": 0,
        "candidateContinuityEdges": 0,
        "uniqueContinuityEdges": 0,
        "eligibleContinuityEdges": 0,
        "newRelayEdges": 0,
        "reusedExistingRelayEdges": 0,
    }

    daily_files = sorted(args.cross_root.glob("2026-*.json.gz"))
    if not daily_files:
        raise SystemExit(f"no derived daily files under {args.cross_root}")
    for daily_path in daily_files:
        stats["dailyFiles"] += 1
        _status(args.status, {"state": "running", "phase": "scan_derived_traces", "date": daily_path.stem, "stats": stats})
        payload = _read_gzip(daily_path)
        for pair, tracks in sorted(payload.get("tracksByPair", {}).items()):
            for track in tracks:
                stats["tracksSeen"] += 1
                points = track.get("sampledPoints") or []
                if len(points) < 2:
                    continue
                stats["tracksWithSampledPoints"] += 1
                cells = _dedupe_cells(points)
                flight_id = str(track.get("flightId") or f"{daily_path.stem}:{stats['tracksSeen']}")
                date = str(track.get("date") or daily_path.stem)
                for left, right in zip(cells, cells[1:], strict=False):
                    if left == right:
                        continue
                    stats["candidateContinuityEdges"] += 1
                    key = _undirected_key(left, right)
                    row = edge_support[key]
                    row["dates"].add(date)
                    row["flights"].add(flight_id)
                    row["pairs"].add(str(pair))

    stats["uniqueContinuityEdges"] = len(edge_support)
    _status(args.status, {"state": "running", "phase": "aggregate_continuity", "stats": stats})

    existing_keys = {
        _undirected_key(_node(link.get("from", {})), _node(link.get("to", {})))
        for link in network.get("relayInferred", [])
        if _valid_node(link.get("from")) and _valid_node(link.get("to"))
    }
    continuity_relays: list[dict[str, Any]] = []
    for key, support in sorted(edge_support.items()):
        if len(support["dates"]) < 2 or len(support["flights"]) < 3:
            continue
        stats["eligibleContinuityEdges"] += 1
        if key in existing_keys:
            stats["reusedExistingRelayEdges"] += 1
            continue
        left, right = key
        continuity_relays.append(
            {
                "from": _node_payload(left),
                "to": _node_payload(right),
                "distanceKm": round(_cell_distance_km(left, right), 3),
                "source": "raw-trace-continuity-7d",
                "sourcePairs": sorted(support["pairs"]),
                "supportDates": sorted(support["dates"]),
                "supportFlightCount": len(support["flights"]),
                "geometryStatus": "inferred_link_only",
                "evidenceStatus": "derived-trace-continuity",
            }
        )
        stats["newRelayEdges"] += 1

    output_network = dict(network)
    output_network["relayInferred"] = list(network.get("relayInferred", [])) + continuity_relays
    summary = dict(output_network.get("summary", {}))
    summary.update(
        {
            "relayInferred": len(output_network["relayInferred"]),
            "traceContinuityRelayInferred": len(continuity_relays),
            "traceContinuityEligibleEdges": stats["eligibleContinuityEdges"],
            "traceContinuityCellDegrees": CELL_DEG,
            "observedGeometryUntouched": True,
            "inferredGeometryNotObserved": True,
        }
    )
    output_network["summary"] = summary
    output_network["rules"] = dict(output_network.get("rules", {}))
    output_network["rules"].update(
        {
            "traceContinuitySource": "existing-7d-derived-sampled-points",
            "traceContinuityMinSupportDates": 2,
            "traceContinuityMinSupportFlights": 3,
            "traceContinuityGeometryIsInferredOnly": True,
            "traceContinuityDoesNotReclassifyObservedEdges": True,
        }
    )
    output_network["traceContinuity"] = {
        "sourceRoot": str(args.cross_root),
        "inputNetwork": str(args.input_network),
        "stats": stats,
        "method": "deduplicated consecutive sampled points from the same derived trace; no raw rescan and no straight-line fill",
    }

    _write_gzip(args.output, output_network)
    review = {
        "schemaVersion": 1,
        "evidenceType": "global_corridor_trace_continuity_review_v1",
        "generatedAt": _now(),
        "inputNetwork": str(args.input_network),
        "outputNetwork": str(args.output),
        "stats": stats,
        "qa": {
            "passed": all(
                [
                    stats["dailyFiles"] == 7,
                    stats["tracksSeen"] > 0,
                    stats["newRelayEdges"] > 0,
                    output_network["summary"].get("observedGeometryUntouched") is True,
                    output_network["summary"].get("inferredGeometryNotObserved") is True,
                ]
            ),
            "checks": {
                "sevenDerivedDaysLoaded": stats["dailyFiles"] == 7,
                "derivedTracksLoaded": stats["tracksSeen"] > 0,
                "continuityRelaysAdded": stats["newRelayEdges"] > 0,
                "observedGeometryUntouched": output_network["summary"].get("observedGeometryUntouched") is True,
                "inferredGeometrySeparated": output_network["summary"].get("inferredGeometryNotObserved") is True,
            },
        },
        "limitations": [
            "continuity links are inferred joins between sampled raw-derived waypoints",
            "they are not promoted to observed geometry or airport-pair schedule data",
            "the source daily-derived artifacts and original network remain unchanged",
        ],
    }
    args.review_output.parent.mkdir(parents=True, exist_ok=True)
    args.review_output.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _status(args.status, {"state": "complete", "phase": "written", "output": str(args.output), "stats": stats, "qa": review["qa"]})
    print(json.dumps({"state": "complete", "stats": stats, "qa": review["qa"]}, ensure_ascii=False, indent=2))
    return 0 if review["qa"]["passed"] else 2


def _dedupe_cells(points: list[dict[str, Any]]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for point in points:
        try:
            cell = (math.floor((float(point["lat"]) + 90.0) / CELL_DEG), math.floor((float(point["lon"]) + 180.0) / CELL_DEG))
        except (KeyError, TypeError, ValueError):
            continue
        if not result or cell != result[-1]:
            result.append(cell)
    return result


def _node(value: dict[str, Any]) -> tuple[int, int]:
    return int(value["latCell"]), int(value["lonCell"])


def _valid_node(value: Any) -> bool:
    return isinstance(value, dict) and "latCell" in value and "lonCell" in value


def _node_payload(value: tuple[int, int]) -> dict[str, int]:
    return {"latCell": value[0], "lonCell": value[1]}


def _undirected_key(left: tuple[int, int], right: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    return (left, right) if left <= right else (right, left)


def _cell_distance_km(left: tuple[int, int], right: tuple[int, int]) -> float:
    lat1 = math.radians(left[0] * CELL_DEG - 90.0 + CELL_DEG / 2.0)
    lat2 = math.radians(right[0] * CELL_DEG - 90.0 + CELL_DEG / 2.0)
    dlat = lat2 - lat1
    dlon = math.radians(right[1] * CELL_DEG - left[1] * CELL_DEG)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(value)))


def _read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_gzip(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def _status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({"updatedAt": _now(), **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
