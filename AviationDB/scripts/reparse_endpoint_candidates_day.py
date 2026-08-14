#!/usr/bin/env python3
"""Reparse only airport endpoint candidates from one retained ADS-B day.

This is intentionally separate from corridor-edge processing.  It fixes the
old 400 km airport-nearest-label scope without rebuilding the 0.25 degree
observed edge set.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from aviationdb.observed_routes import AirportIndex, parse_trace_points  # noqa: E402
from process_raw_corridor_day import (  # noqa: E402
    HashingConcatenatedBinaryIO,
    _callsign_segments,
    _iter_trace_payloads_from_tarfile,
    _split_legs_fast,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--airport-index", type=Path, default=ROOT / "shared/offline-packs/core-global/airports-index.json")
    parser.add_argument("--endpoint-max-km", type=float, default=150.0)
    parser.add_argument("--min-points", type=int, default=8)
    parser.add_argument("--max-trace-gap-s", type=float, default=2700.0)
    args = parser.parse_args()

    parts = sorted(
        item for item in args.raw_dir.iterdir()
        if item.is_file() and item.name.endswith((".tar.aa", ".tar.ab", ".tar.ac", ".tar.ad", ".tar.ae", ".tar.af"))
    )
    if not parts or any(item.stat().st_size == 0 for item in parts):
        raise SystemExit(f"incomplete raw parts: {args.raw_dir}")

    airports = AirportIndex.from_json(args.airport_index)
    endpoint_cache: dict[tuple[int, int], object] = {}
    pairs: dict[tuple[str, str], dict[str, object]] = {}
    stats = {"tracesSeen": 0, "tracesParsed": 0, "parseErrors": 0, "legsSeen": 0, "legsAccepted": 0, "endpointPairsTouched": 0}
    stream = HashingConcatenatedBinaryIO(parts)
    with stream:
        import io
        with io.BufferedReader(stream, buffer_size=1024 * 1024) as buffered:
            for _, payload in _iter_trace_payloads_from_tarfile(buffered, label="+".join(item.name for item in parts[:2])):
                stats["tracesSeen"] += 1
                try:
                    trace = json.loads(payload)
                    points = parse_trace_points(trace)
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    stats["parseErrors"] += 1
                    continue
                stats["tracesParsed"] += 1
                for leg in _split_legs_fast(points, args.min_points, args.max_trace_gap_s):
                    stats["legsSeen"] += 1
                    if len(leg) < args.min_points:
                        continue
                    stats["legsAccepted"] += 1
                    origin = nearest(airports, leg[0].lat, leg[0].lon, args.endpoint_max_km, endpoint_cache)
                    destination = nearest(airports, leg[-1].lat, leg[-1].lon, args.endpoint_max_km, endpoint_cache)
                    if not origin or not destination or origin.airport.iata == destination.airport.iata:
                        continue
                    key = (origin.airport.iata, destination.airport.iata)
                    row = pairs.setdefault(key, {"legs": 0, "aircraft": set(), "callsigns": set(), "originDistances": [], "destinationDistances": []})
                    row["legs"] += 1
                    row["aircraft"].add(str(trace.get("icao") or "").strip().lower())
                    row["callsigns"].update(_callsign_segments(leg))
                    row["originDistances"].append(round(origin.distance_km, 3))
                    row["destinationDistances"].append(round(destination.distance_km, 3))
                    stats["endpointPairsTouched"] += 1

    endpoint_rows = []
    for (origin, destination), row in sorted(pairs.items()):
        endpoint_rows.append({
            "originIata": origin,
            "destinationIata": destination,
            "supportLegs": row["legs"],
            "aircraftExamples": sorted(value for value in row["aircraft"] if value)[:24],
            "callsignExamples": sorted(value for value in row["callsigns"] if value)[:24],
            "originEndpointDistanceKm": {"min": min(row["originDistances"]), "max": max(row["originDistances"])},
            "destinationEndpointDistanceKm": {"min": min(row["destinationDistances"]), "max": max(row["destinationDistances"])},
        })
    payload = {
        "schemaVersion": 1,
        "evidenceType": "raw_derived_endpoint_reparse",
        "date": args.date,
        "generatedAt": datetime.now(UTC).isoformat(),
        "method": {"endpointMaxKm": args.endpoint_max_km, "minPoints": args.min_points, "maxTraceGapSeconds": args.max_trace_gap_s, "ifrValidationUsed": False, "corridorEdgesRebuilt": False},
        "input": {"rawDir": str(args.raw_dir), "parts": [{"path": str(item), "bytes": item.stat().st_size} for item in parts], "combinedSha256": stream.hexdigest()},
        "stats": stats,
        "endpointCandidates": endpoint_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(args.output)
    print(json.dumps({"state": "complete", "date": args.date, "stats": stats, "output": str(args.output)}, ensure_ascii=False))
    return 0


def nearest(index: AirportIndex, lat: float, lon: float, max_km: float, cache: dict[tuple[int, int], object]):
    key = (round(lat * 4), round(lon * 4))
    if key not in cache:
        cache[key] = index.nearest(lat, lon, max_km)
    return cache[key]


if __name__ == "__main__":
    raise SystemExit(main())
