#!/usr/bin/env python3
"""Targeted raw-trace investigation for the 2026-08-02 KHH/NRT evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))

from aviationdb.observed_routes import (  # noqa: E402
    Airport,
    AirportIndex,
    BuildOptions,
    TracePoint,
    haversine_km,
    iter_trace_payloads_from_split_tar,
    parse_trace_points,
    route_distance_km,
    split_legs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Search 2026-08-02 raw ADS-B traces for AIQ234 and KHH-NRT candidates.")
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--airport-index", type=Path, default=ROOT / "shared/offline-packs/core-global/airports-index.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    parts = sorted(
        path
        for path in args.release_dir.glob("*.tar.*")
        if path.name.endswith((".tar.aa", ".tar.ab", ".tar.ac", ".tar.ad", ".tar.ae", ".tar.af"))
    )
    if len(parts) < 2:
        raise SystemExit(f"Expected split tar parts in {args.release_dir}; found {len(parts)}")
    airport_index = AirportIndex.from_json(args.airport_index)
    airports = {airport.iata: airport for airport in airport_index.airports}
    khh = airports["KHH"]
    nrt = airports["NRT"]
    options = BuildOptions(max_airport_km=150, min_points=8, min_route_km=120, max_trace_gap_s=2700, max_track_detour_ratio=2.6)

    traces_seen = 0
    parse_errors = 0
    token_matches: list[dict[str, Any]] = []
    raw_token_trace_sources: set[str] = set()
    corridor_matches: list[dict[str, Any]] = []
    callsigns: Counter[str] = Counter()

    for source_name, payload in iter_trace_payloads_from_split_tar(parts):
        traces_seen += 1
        upper_payload = payload.upper()
        raw_tokens = [token.decode() for token in (b"AIQ234", b"FD234") if token in upper_payload]
        if raw_tokens:
            raw_token_trace_sources.add(source_name)
        try:
            trace = json.loads(payload)
            points = parse_trace_points(trace)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            parse_errors += 1
            continue
        callsign = _trace_callsign(trace, points)
        if callsign:
            callsigns[callsign] += 1
        for leg in split_legs(points, options):
            summary = _leg_summary(leg, trace, source_name, khh, nrt, airport_index)
            for window_callsign, window in _callsign_windows(leg):
                if window_callsign in {"AIQ234", "FD234"}:
                    exact = _leg_summary(window, trace, source_name, khh, nrt, airport_index)
                    exact["matchedTokens"] = [window_callsign]
                    token_matches.append(exact)
            if summary["minKhhKm"] <= 300 and summary["minNrtKm"] <= 300 and summary["distanceKm"] >= 1000:
                corridor_matches.append(summary)
        if traces_seen % 10000 == 0:
            print(f"scanned {traces_seen} traces", file=sys.stderr, flush=True)

    corridor_matches.sort(key=lambda row: (row["minKhhKm"] + row["minNrtKm"], -row["distanceKm"]))
    token_matches.sort(key=lambda row: (row["minKhhKm"] + row["minNrtKm"], -row["distanceKm"]))
    result = {
        "schemaVersion": 1,
        "date": "2026-08-02",
        "source": [str(path) for path in parts],
        "target": {"flight": "AIQ234 / FD234", "origin": "KHH", "destination": "NRT"},
        "summary": {
            "tracesSeen": traces_seen,
            "parseErrors": parse_errors,
            "tokenMatchSegments": len(token_matches),
            "rawTokenTraceSources": len(raw_token_trace_sources),
            "khhNrtCorridorLegs": len(corridor_matches),
        },
        "tokenMatches": token_matches[:100],
        "corridorMatches": corridor_matches[:200],
        "callsignMatches": [[key, value] for key, value in callsigns.most_common() if re.search(r"AIQ|FD", key, re.I)][:100],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


def _trace_callsign(trace: dict[str, Any], points: list[TracePoint]) -> str | None:
    for key in ("flight", "callsign", "callSign"):
        value = trace.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    values = [point.callsign.strip().upper() for point in points if point.callsign and point.callsign.strip()]
    return values[0] if values else None


def _callsign_windows(points: list[TracePoint]) -> list[tuple[str, list[TracePoint]]]:
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


def _leg_summary(
    leg: list[TracePoint],
    trace: dict[str, Any],
    source_name: str,
    khh: Airport,
    nrt: Airport,
    airport_index: AirportIndex,
) -> dict[str, Any]:
    khh_distances = [haversine_km(point.lat, point.lon, khh.lat, khh.lon) for point in leg]
    nrt_distances = [haversine_km(point.lat, point.lon, nrt.lat, nrt.lon) for point in leg]
    khh_index = min(range(len(leg)), key=khh_distances.__getitem__)
    nrt_index = min(range(len(leg)), key=nrt_distances.__getitem__)
    first = leg[0]
    last = leg[-1]
    nearest_first = airport_index.nearest(first.lat, first.lon, 300)
    nearest_last = airport_index.nearest(last.lat, last.lon, 300)
    return {
        "callsign": _trace_callsign(trace, leg),
        "icao24": trace.get("icao24") or trace.get("hex"),
        "sourceFile": source_name,
        "points": len(leg),
        "distanceKm": round(route_distance_km([(point.lat, point.lon) for point in leg]), 1),
        "minKhhKm": round(khh_distances[khh_index], 1),
        "minNrtKm": round(nrt_distances[nrt_index], 1),
        "khhClosestIndex": khh_index,
        "nrtClosestIndex": nrt_index,
        "direction": "KHH-to-NRT" if khh_index < nrt_index else "NRT-to-KHH" if nrt_index < khh_index else "undetermined",
        "nearestFirst": _airport_payload(nearest_first),
        "nearestLast": _airport_payload(nearest_last),
        "firstPoint": _point_payload(first),
        "lastPoint": _point_payload(last),
        "khhClosestPoint": _point_payload(leg[khh_index]),
        "nrtClosestPoint": _point_payload(leg[nrt_index]),
        "sampledTrack": [_point_payload(point) for point in _sample_points(leg, 160)],
    }


def _sample_points(points: list[TracePoint], limit: int) -> list[TracePoint]:
    if len(points) <= limit:
        return points
    stride = (len(points) - 1) / (limit - 1)
    return [points[round(index * stride)] for index in range(limit)]


def _point_payload(point: TracePoint) -> dict[str, Any]:
    return {
        "elapsedS": round(point.elapsed_s, 1),
        "lat": round(point.lat, 6),
        "lon": round(point.lon, 6),
        "altitudeFt": point.altitude_ft,
        "groundSpeedKt": point.ground_speed_kt,
        "trackDeg": point.track_deg,
    }


def _airport_payload(nearest: Any) -> dict[str, Any] | None:
    if nearest is None:
        return None
    return {
        "iata": nearest.airport.iata,
        "icao": nearest.airport.icao,
        "name": nearest.airport.name,
        "distanceKm": round(nearest.distance_km, 1),
    }


if __name__ == "__main__":
    raise SystemExit(main())
