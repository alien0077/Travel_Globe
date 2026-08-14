#!/usr/bin/env python3
"""Extract all remaining cross-continent corridor candidates in one raw pass.

This is deliberately independent of airport-endpoint labels and IFR output.  A
trace is retained when its observed geometry enters two distinct continental
gates and the gate-to-gate distance is substantial.  Every date is written as
an atomic checkpoint so an interrupted run resumes without rereading finished
dates.  Asia-NorthAmerica is counted but omitted from the output because it
already has a dedicated, separately audited extraction.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from process_raw_corridor_day import HashingConcatenatedBinaryIO, _split_legs_fast
from aviationdb.observed_routes import _iter_trace_payloads_from_tarfile, parse_trace_points

DATES = [
    "2026-08-02", "2026-08-01", "2026-07-31", "2026-07-30",
    "2026-07-29", "2026-07-28", "2026-07-27",
]

# Broad gates are observation gates, not airport boundaries.  The order is
# only used to make overlap deterministic; a point may belong to more than one
# gate at a boundary and the pair is still required to span a long distance.
REGION_BOXES: dict[str, tuple[tuple[float, float, float, float], ...]] = {
    "NorthAmerica": ((15.0, 72.0, -180.0, -50.0),),
    "SouthAmerica": ((-56.0, 15.0, -90.0, -30.0),),
    "Europe": ((35.0, 72.0, -25.0, 45.0),),
    "Africa": ((-35.0, 37.0, -20.0, 52.0),),
    "Asia": ((-10.0, 25.0, 45.0, 145.0), (20.0, 60.0, 45.0, 180.0)),
    "Oceania": ((-50.0, 0.0, 110.0, 180.0), (-50.0, 0.0, -180.0, -130.0)),
}
REGION_ORDER = tuple(REGION_BOXES)
EXCLUDED_PAIR: str | None = "Asia-NorthAmerica"
CELL_DEG = 0.25
MIN_GATE_DISTANCE_KM = 2000.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--cell-deg", type=float, default=0.25)
    parser.add_argument("--include-asia-northamerica", action="store_true")
    args = parser.parse_args()
    global CELL_DEG, EXCLUDED_PAIR
    CELL_DEG = args.cell_deg
    EXCLUDED_PAIR = None if args.include_asia_northamerica else "Asia-NorthAmerica"
    if abs(CELL_DEG - 0.25) > 1e-9:
        raise SystemExit("--cell-deg must be exactly 0.25 for the global corridor pipeline")
    args.output_root.mkdir(parents=True, exist_ok=True)
    _status(args.status, {"state": "running", "phase": "preflight", "dates": DATES})
    for date in DATES:
        output = args.output_root / f"{date}.json.gz"
        if output.exists() and _valid(output, date):
            _status(args.status, {"state": "running", "phase": "date_reused", "date": date})
            continue
        _process_date(date, args.raw_root / date, output, args.status)
    _aggregate(args.output_root, args.status)
    _status(args.status, {"state": "complete", "phase": "written", "dates": DATES})
    return 0


def _process_date(date: str, raw_dir: Path, output: Path, status: Path) -> None:
    parts = sorted(
        p for p in raw_dir.iterdir() if p.is_file() and p.name.endswith(
            (".tar.aa", ".tar.ab", ".tar.ac", ".tar.ad", ".tar.ae", ".tar.af")
        )
    )
    if not parts:
        raise SystemExit(f"missing raw parts: {date}")
    tracks_by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    stats = {
        "tracesSeen": 0, "tracesParsed": 0, "parseErrors": 0,
        "legsSeen": 0, "candidateFlights": 0, "excludedAsiaNorthAmerica": 0,
    }
    started = time.monotonic()
    stream = HashingConcatenatedBinaryIO(parts)
    with stream, io.BufferedReader(stream, buffer_size=1024 * 1024) as buffered:
        for source, payload in _iter_trace_payloads_from_tarfile(
            buffered, label="+".join(p.name for p in parts[:2])
        ):
            stats["tracesSeen"] += 1
            try:
                trace = json.loads(payload)
                points = parse_trace_points(trace)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                stats["parseErrors"] += 1
                continue
            stats["tracesParsed"] += 1
            icao = str(trace.get("icao") or "").strip().lower() or None
            for leg in _split_legs_fast(points, 8, 21600):
                stats["legsSeen"] += 1
                matches = _cross_continent_matches(leg)
                if not matches:
                    continue
                stats["candidateFlights"] += 1
                callsign = _best_callsign(leg)
                for pair, match in matches.items():
                    if EXCLUDED_PAIR and pair == EXCLUDED_PAIR:
                        stats["excludedAsiaNorthAmerica"] += 1
                        continue
                    tracks_by_pair[pair].append(
                        _track(date, source, icao, callsign, leg, match)
                    )
            if stats["tracesSeen"] % 10000 == 0:
                _status(status, {
                    "state": "running", "phase": "scan", "date": date,
                    "stats": stats,
                    "pairCounts": {key: len(value) for key, value in tracks_by_pair.items()},
                    "wallSeconds": round(time.monotonic() - started, 1),
                })
    payload = {
        "schemaVersion": 1,
        "evidenceType": "raw_derived_global_cross_continent_flights_v1",
        "date": date,
        "cellDegrees": CELL_DEG,
        "stats": stats,
        "tracksByPair": dict(sorted(tracks_by_pair.items())),
    }
    _write_gzip(output, payload)
    _status(status, {
        "state": "running", "phase": "date_complete", "date": date,
        "stats": stats,
        "pairCounts": {key: len(value) for key, value in tracks_by_pair.items()},
        "wallSeconds": round(time.monotonic() - started, 1),
    })


def _cross_continent_matches(points: list[Any]) -> dict[str, dict[str, Any]]:
    occurrences: dict[str, list[int]] = defaultdict(list)
    for index, point in enumerate(points):
        for region in REGION_ORDER:
            if any(_in_box(point.lat, point.lon, box) for box in REGION_BOXES[region]):
                occurrences[region].append(index)
    regions = [region for region in REGION_ORDER if occurrences.get(region)]
    if len(regions) < 2:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for left_index, left in enumerate(regions):
        for right in regions[left_index + 1:]:
            first = min(occurrences[left])
            last = max(occurrences[right])
            direction = f"{left}-{right}" if first <= last else f"{right}-{left}"
            start = points[first]
            end = points[last]
            distance = _rough_distance(start, end)
            if distance < MIN_GATE_DISTANCE_KM:
                continue
            pair = "-".join(sorted((left, right)))
            result[pair] = {
                "direction": direction,
                "firstRegion": left if first <= last else right,
                "lastRegion": right if first <= last else left,
                "gateSpanKm": round(distance, 1),
                "gateStartIndex": min(first, last),
                "gateEndIndex": max(first, last),
            }
    return result


def _best_callsign(points: list[Any]) -> str:
    values = [str(point.callsign or "").strip().upper() for point in points]
    counts = Counter(value for value in values if value)
    return counts.most_common(1)[0][0] if counts else "UNKNOWN"


def _track(date: str, source: str, icao: str | None, callsign: str, points: list[Any], match: dict[str, Any]) -> dict[str, Any]:
    flight_id = f"{date}:{icao or 'unknown'}:{callsign}:{source.split(':', 1)[0]}"
    return {
        "flightId": flight_id, "date": date, "icao": icao, "callsign": callsign,
        "sourceFile": source, **match, "pointCount": len(points),
        "sampledPoints": _sample(points, 96), "observedEdges": _edges(points),
    }


def _edges(points: list[Any]) -> list[list[int]]:
    result: list[list[int]] = []
    seen: set[tuple[int, int, int, int]] = set()
    previous = None
    for point in points:
        cell = (math.floor((point.lat + 90) / CELL_DEG), math.floor((point.lon + 180) / CELL_DEG))
        if previous and cell != previous and abs(cell[0] - previous[0]) <= 4 and abs(cell[1] - previous[1]) <= 4:
            edge = (*previous, *cell)
            if edge not in seen:
                seen.add(edge)
                result.append(list(edge))
        previous = cell
    return result


def _aggregate(root: Path, status: Path) -> None:
    tracks_by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    support: dict[str, dict[tuple[int, int, int, int], dict[str, set[str]]]] = defaultdict(
        lambda: defaultdict(lambda: {"dates": set(), "flights": set()})
    )
    for path in sorted(root.glob("2026-*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        for pair, tracks in payload.get("tracksByPair", {}).items():
            tracks_by_pair[pair].extend(tracks)
            for track in tracks:
                for edge in track.get("observedEdges", []):
                    row = support[pair][tuple(edge)]
                    row["dates"].add(track["date"])
                    row["flights"].add(track["flightId"])
    pair_summaries: dict[str, dict[str, int]] = {}
    pair_payloads: dict[str, dict[str, Any]] = {}
    for pair, tracks in sorted(tracks_by_pair.items()):
        edges = []
        for edge, row in support[pair].items():
            edges.append({
                "from": {"latCell": edge[0], "lonCell": edge[1]},
                "to": {"latCell": edge[2], "lonCell": edge[3]},
                "supportDates": sorted(row["dates"]),
                "supportFlightCount": len(row["flights"]),
                "classification": "shared_observed" if len(row["dates"]) >= 2 and len(row["flights"]) >= 3 else "single_or_weak_observed",
            })
        summary = {
            "candidateFlights": len(tracks),
            "sharedEdges": sum(edge["classification"] == "shared_observed" for edge in edges),
            "totalObservedEdges": len(edges),
            "airportEndpointsUsed": False, "ifrUsed": False,
        }
        pair_summaries[pair] = summary
        pair_payloads[pair] = {"summary": summary, "flights": tracks, "edges": edges}
    _write_gzip(root / "global-cross-continent-corridors.json.gz", {
        "schemaVersion": 1,
        "evidenceType": "raw_derived_global_cross_continent_shared_corridors_v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {"pairs": len(pair_payloads), "pairSummaries": pair_summaries, "excludedPair": EXCLUDED_PAIR, "cellDegrees": CELL_DEG},
        "pairs": pair_payloads,
        "limitations": [
            "continent gates are geographic observation gates, not airport endpoints",
            "Asia-NorthAmerica is excluded here because its dedicated extraction is retained separately",
            "missing middle geometry is not invented; only observed local edges are emitted",
            "shared_observed requires at least two dates and three flight identities",
        ],
    })
    _status(status, {"state": "running", "phase": "aggregate_complete", "summary": {"pairs": len(pair_payloads), "pairSummaries": pair_summaries}})


def _in_box(lat: float, lon: float, box: tuple[float, float, float, float]) -> bool:
    return box[0] <= lat <= box[1] and box[2] <= lon <= box[3]


def _rough_distance(a: Any, b: Any) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(((b.lon - a.lon + 180.0) % 360.0) - 180.0)
    value = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return 6371.0088 * 2.0 * math.asin(min(1.0, math.sqrt(value)))


def _sample(points: list[Any], limit: int) -> list[dict[str, Any]]:
    indexes = range(len(points)) if len(points) <= limit else sorted({round(i * (len(points) - 1) / (limit - 1)) for i in range(limit)})
    return [{"lat": round(points[i].lat, 5), "lon": round(points[i].lon, 5), "elapsedS": points[i].elapsed_s, "trackDeg": points[i].track_deg} for i in indexes]


def _write_gzip(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def _valid(path: Path, date: str) -> bool:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        declared = payload.get("method", {}).get("cellDegrees", payload.get("cellDegrees"))
        legacy_025 = declared is None and (path.parent / ".resolution-0.25.json").is_file()
        return payload.get("date") == date and payload.get("evidenceType") == "raw_derived_global_cross_continent_flights_v1" and (legacy_025 or abs(float(declared) - 0.25) < 1e-9)
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({"updatedAt": datetime.now(timezone.utc).isoformat(), **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
