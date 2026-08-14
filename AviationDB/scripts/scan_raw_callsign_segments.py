#!/usr/bin/env python3
"""Scan split ADS-B raw data for exact point-level callsign segments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))

from aviationdb.observed_routes import (  # noqa: E402
    AirportIndex,
    BuildOptions,
    TracePoint,
    haversine_km,
    iter_trace_payloads_from_split_tar,
    parse_trace_points,
    split_legs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Find exact callsign segments in ADS-B raw split tar data.")
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--callsign", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    callsigns = {value.strip().upper() for value in args.callsign if value.strip()}
    parts = sorted(
        path
        for path in args.release_dir.glob("*.tar.*")
        if path.name.endswith((".tar.aa", ".tar.ab", ".tar.ac", ".tar.ad", ".tar.ae", ".tar.af"))
    )
    if len(parts) < 2:
        raise SystemExit(f"Expected split tar parts in {args.release_dir}; found {len(parts)}")
    airports = {airport.iata: airport for airport in AirportIndex.from_json(ROOT / "shared/offline-packs/core-global/airports-index.json").airports}
    khh, nrt = airports["KHH"], airports["NRT"]
    matches: list[dict[str, Any]] = []
    trace_count = 0
    for source, payload in iter_trace_payloads_from_split_tar(parts):
        upper = payload.upper()
        if not any(callsign.encode() in upper for callsign in callsigns):
            continue
        trace = json.loads(payload)
        points = parse_trace_points(trace)
        trace_count += 1
        for leg in split_legs(points, BuildOptions(max_trace_gap_s=2700)):
            for callsign, segment in callsign_windows(leg):
                if callsign in callsigns and len(segment) >= 8:
                    matches.append(summarize(callsign, segment, source, khh, nrt))
    result = {
        "schemaVersion": 1,
        "callsigns": sorted(callsigns),
        "traceMatches": trace_count,
        "segments": matches,
        "sourceParts": [str(path) for path in parts],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"traceMatches": trace_count, "segments": len(matches), "output": str(args.output)}, ensure_ascii=False))
    return 0


def callsign_windows(points: list[TracePoint]) -> list[tuple[str, list[TracePoint]]]:
    windows: list[tuple[str, list[TracePoint]]] = []
    current: str | None = None
    start = 0
    for index, point in enumerate(points):
        callsign = point.callsign.strip().upper() if point.callsign else None
        if not callsign or callsign == current:
            continue
        if current and index - start >= 8:
            windows.append((current, points[start:index]))
        current = callsign
        start = 0 if not windows and index < 8 else index
    if current and len(points) - start >= 8:
        windows.append((current, points[start:]))
    return windows


def summarize(callsign: str, points: list[TracePoint], source: str, khh: Any, nrt: Any) -> dict[str, Any]:
    khh_distances = [haversine_km(point.lat, point.lon, khh.lat, khh.lon) for point in points]
    nrt_distances = [haversine_km(point.lat, point.lon, nrt.lat, nrt.lon) for point in points]
    khh_index = min(range(len(points)), key=khh_distances.__getitem__)
    nrt_index = min(range(len(points)), key=nrt_distances.__getitem__)
    return {
        "callsign": callsign,
        "sourceFile": source,
        "points": len(points),
        "direction": "KHH-NRT" if khh_index < nrt_index else "NRT-KHH" if nrt_index < khh_index else "undetermined",
        "minKhhKm": round(khh_distances[khh_index], 1),
        "minNrtKm": round(nrt_distances[nrt_index], 1),
        "firstPoint": {"lat": points[0].lat, "lon": points[0].lon, "elapsedS": points[0].elapsed_s},
        "lastPoint": {"lat": points[-1].lat, "lon": points[-1].lon, "elapsedS": points[-1].elapsed_s},
        "khhClosestPoint": {"lat": points[khh_index].lat, "lon": points[khh_index].lon, "elapsedS": points[khh_index].elapsed_s},
        "nrtClosestPoint": {"lat": points[nrt_index].lat, "lon": points[nrt_index].lon, "elapsedS": points[nrt_index].elapsed_s},
    }


if __name__ == "__main__":
    raise SystemExit(main())
