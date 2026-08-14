#!/usr/bin/env python3
"""Process one retained ADS-B release into raw-derived corridor evidence.

This stage deliberately does not read IFR validation output or airport-pair
labels. It performs one streaming pass over the split tar and emits immutable,
date-level evidence for the later global corridor merge.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import sys
import tarfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))

from aviationdb.observed_routes import (  # noqa: E402
    AirportIndex,
    BuildOptions,
    _iter_trace_payloads_from_tarfile,
    parse_trace_points,
)

CELL_DEG = 0.25
MAX_EDGE_JUMP_CELLS = 4
MAX_EXAMPLES = 24


class HashingConcatenatedBinaryIO(io.RawIOBase):
    """Concatenate split parts and hash bytes as tarfile consumes them."""

    def __init__(self, paths: list[Path]) -> None:
        super().__init__()
        self.paths = paths
        self.index = 0
        self.current = None
        self.digest = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int:
        view = memoryview(buffer)
        total = 0
        while total < len(view):
            if self.current is None:
                if self.index >= len(self.paths):
                    break
                self.current = self.paths[self.index].open("rb")
                self.index += 1
            count = self.current.readinto(view[total:])
            if not count:
                self.current.close()
                self.current = None
                continue
            self.digest.update(view[total : total + count])
            total += count
        return total

    def close(self) -> None:
        if self.current is not None:
            self.current.close()
            self.current = None
        super().close()

    def hexdigest(self) -> str:
        return self.digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build one-pass raw-derived corridor evidence for one date.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--airport-index", type=Path, default=ROOT / "shared/offline-packs/core-global/airports-index.json")
    parser.add_argument("--min-points", type=int, default=8)
    parser.add_argument("--max-trace-gap-s", type=float, default=2700)
    parser.add_argument("--endpoint-max-km", type=float, default=400.0)
    parser.add_argument("--cell-deg", type=float, default=0.25)
    parser.add_argument("--progress", type=Path)
    parser.add_argument("--checkpoint-dir", type=Path)
    args = parser.parse_args()
    if abs(args.cell_deg - 0.25) > 1e-9:
        raise SystemExit("--cell-deg must be exactly 0.25 for the global corridor pipeline")

    # release_parts_from_dir() intentionally accepts generic tar-like names,
    # but this raw cache also contains sidecar .headers files.  They must never
    # enter the concatenated tar stream.
    parts = sorted(
        item
        for item in args.raw_dir.iterdir()
        if item.is_file()
        and item.name.endswith((".tar.aa", ".tar.ab", ".tar.ac", ".tar.ad", ".tar.ae", ".tar.af"))
    )
    if not parts:
        raise SystemExit(f"No complete split tar parts found in {args.raw_dir}")
    if any(path.stat().st_size == 0 for path in parts):
        raise SystemExit(f"Empty raw part in {args.raw_dir}")

    airport_index = AirportIndex.from_json(args.airport_index)
    endpoint_cache: dict[tuple[int, int], Any] = {}
    checkpoint_dir = args.checkpoint_dir or args.output.parent / f".{args.date}-chunks"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    chunk_paths = sorted(checkpoint_dir.glob("chunk-*.json.gz"))
    resume_traces = 0
    stats = {
        "tracesSeen": 0,
        "tracesParsed": 0,
        "parseErrors": 0,
        "legsSeen": 0,
        "legsAccepted": 0,
        "pointsSeen": 0,
        "edgesTouched": 0,
        "callsignSegments": 0,
    }
    source_files: set[str] = set()
    for chunk_path in chunk_paths:
        chunk = _read_json_gzip(chunk_path)
        chunk_stats = chunk.get("stats", {})
        resume_traces += int(chunk_stats.get("tracesSeen", 0))
        for key in stats:
            stats[key] += int(chunk_stats.get(key, 0))
        source_files.update(str(value) for value in chunk.get("sourceFiles", []))
    started = time.monotonic()
    edge_stats: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    endpoint_stats: dict[tuple[str, str], dict[str, Any]] = {}
    base_stats = stats.copy()
    raw_trace_index = 0
    traces_since_checkpoint = 0
    next_chunk_index = len(chunk_paths) + 1

    stream = HashingConcatenatedBinaryIO(parts)
    with stream, io.BufferedReader(stream, buffer_size=1024 * 1024) as buffered:
        for source_name, payload in _iter_trace_payloads_from_tarfile(
            buffered, label="+".join(path.name for path in parts[:2])
        ):
            raw_trace_index += 1
            if raw_trace_index <= resume_traces:
                continue
            stats["tracesSeen"] += 1
            traces_since_checkpoint += 1
            source_files.add(source_name.split(":", 1)[0])
            try:
                trace = json.loads(payload)
                points = parse_trace_points(trace)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                stats["parseErrors"] += 1
                continue
            stats["tracesParsed"] += 1
            stats["pointsSeen"] += len(points)
            for leg in _split_legs_fast(points, args.min_points, args.max_trace_gap_s):
                stats["legsSeen"] += 1
                if len(leg) < args.min_points:
                    continue
                stats["legsAccepted"] += 1
                callsigns = _callsign_segments(leg)
                stats["callsignSegments"] += len(callsigns)
                icao = str(trace.get("icao") or "").strip().lower() or None
                first = leg[0]
                last = leg[-1]
                origin = _nearest_cached(airport_index, first.lat, first.lon, args.endpoint_max_km, endpoint_cache)
                destination = _nearest_cached(airport_index, last.lat, last.lon, args.endpoint_max_km, endpoint_cache)
                if origin and destination and origin.airport.iata != destination.airport.iata:
                    key = (origin.airport.iata, destination.airport.iata)
                    endpoint = endpoint_stats.setdefault(key, _new_endpoint_stat())
                    endpoint["legs"] += 1
                    _add_example(endpoint["aircraft"], icao)
                    for callsign in callsigns:
                        _add_example(endpoint["callsigns"], callsign)

                touched: set[tuple[int, int, int, int]] = set()
                previous_cell: tuple[int, int] | None = None
                for point in leg:
                    current_cell = _cell(point.lat, point.lon)
                    if previous_cell is not None and current_cell != previous_cell:
                        lat_delta = abs(current_cell[0] - previous_cell[0])
                        lon_delta = abs(current_cell[1] - previous_cell[1])
                        if lat_delta <= MAX_EDGE_JUMP_CELLS and lon_delta <= MAX_EDGE_JUMP_CELLS:
                            touched.add((*previous_cell, *current_cell))
                    previous_cell = current_cell
                stats["edgesTouched"] += len(touched)
                for edge in touched:
                    row = edge_stats.setdefault(edge, _new_edge_stat())
                    row["supportLegs"] += 1
                    _add_example(row["aircraft"], icao)
                    for callsign in callsigns:
                        _add_example(row["callsigns"], callsign)
                    if len(row["dates"]) < MAX_EXAMPLES:
                        row["dates"].add(args.date)
            if args.progress and traces_since_checkpoint >= 10000:
                _write_progress(args.progress, args.date, stats, time.monotonic() - started)
            if traces_since_checkpoint >= 10000:
                chunk_path = checkpoint_dir / f"chunk-{next_chunk_index:04d}.json.gz"
                chunk_stats = {key: stats[key] - base_stats[key] for key in stats}
                _write_chunk(chunk_path, chunk_stats, edge_stats, endpoint_stats, source_files)
                next_chunk_index += 1
                base_stats = stats.copy()
                edge_stats = {}
                endpoint_stats = {}
                source_files = set()
                traces_since_checkpoint = 0

    merged_edge_stats: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    merged_endpoint_stats: dict[tuple[str, str], dict[str, Any]] = {}
    merged_source_files: set[str] = set()
    for chunk_path in sorted(checkpoint_dir.glob("chunk-*.json.gz")):
        chunk = _read_json_gzip(chunk_path)
        _merge_chunk_edges(merged_edge_stats, chunk.get("corridorEdges", []))
        _merge_chunk_endpoints(merged_endpoint_stats, chunk.get("endpointCandidates", []))
        merged_source_files.update(str(value) for value in chunk.get("sourceFiles", []))
    _merge_edge_maps(merged_edge_stats, edge_stats)
    _merge_endpoint_maps(merged_endpoint_stats, endpoint_stats)
    merged_source_files.update(source_files)

    payload = {
        "schemaVersion": 1,
        "evidenceType": "raw_derived_unbiased",
        "date": args.date,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "method": {
            "cellDegrees": CELL_DEG,
            "maxEdgeJumpCells": MAX_EDGE_JUMP_CELLS,
            "minPoints": args.min_points,
            "maxTraceGapSeconds": args.max_trace_gap_s,
            "airportEndpointMaxKm": args.endpoint_max_km,
            "airportPairLabelsUsed": False,
            "ifrValidationUsed": False,
            "passesOverRaw": 1,
        },
        "input": {
            "rawDir": str(args.raw_dir),
            "parts": [{"path": str(path), "bytes": path.stat().st_size} for path in parts],
            "combinedSha256": stream.hexdigest(),
            "sourceFiles": sorted(merged_source_files),
        },
        "stats": {**stats, "wallSeconds": round(time.monotonic() - started, 3)},
        "corridorEdges": [_edge_payload(edge, row) for edge, row in sorted(merged_edge_stats.items())],
        "endpointCandidates": [
            {"originIata": key[0], "destinationIata": key[1], **_endpoint_payload(row)}
            for key, row in sorted(merged_endpoint_stats.items())
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(args.output)
    print(json.dumps({"date": args.date, "output": str(args.output), "stats": payload["stats"]}, ensure_ascii=False))
    return 0


def _cell(lat: float, lon: float) -> tuple[int, int]:
    return math.floor((lat + 90.0) / CELL_DEG), math.floor((lon + 180.0) / CELL_DEG)


def _callsign_segments(points: list[Any]) -> list[str]:
    segments: list[str] = []
    previous: str | None = None
    for point in points:
        callsign = point.callsign or previous
        if callsign and callsign != previous:
            segments.append(callsign)
        previous = callsign
    return segments


def _new_edge_stat() -> dict[str, Any]:
    return {"supportLegs": 0, "aircraft": set(), "callsigns": set(), "dates": set()}


def _new_endpoint_stat() -> dict[str, Any]:
    return {"legs": 0, "aircraft": set(), "callsigns": set()}


def _add_example(values: set[str], value: str | None) -> None:
    if value and len(values) < MAX_EXAMPLES:
        values.add(value)


def _edge_payload(edge: tuple[int, int, int, int], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "from": {"latCell": edge[0], "lonCell": edge[1]},
        "to": {"latCell": edge[2], "lonCell": edge[3]},
        "supportLegs": row["supportLegs"],
        "supportAircraftExamples": sorted(row["aircraft"]),
        "supportCallsignExamples": sorted(row["callsigns"]),
        "supportDates": sorted(row["dates"]),
    }


def _endpoint_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "supportLegs": row["legs"],
        "aircraftExamples": sorted(row["aircraft"]),
        "callsignExamples": sorted(row["callsigns"]),
    }


def _read_json_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _write_chunk(
    path: Path,
    stats: dict[str, int],
    edges: dict[tuple[int, int, int, int], dict[str, Any]],
    endpoints: dict[tuple[str, str], dict[str, Any]],
    source_files: set[str],
) -> None:
    payload = {
        "schemaVersion": 1,
        "stats": stats,
        "sourceFiles": sorted(source_files),
        "corridorEdges": [_edge_payload(edge, row) for edge, row in sorted(edges.items())],
        "endpointCandidates": [
            {"originIata": key[0], "destinationIata": key[1], **_endpoint_payload(row)}
            for key, row in sorted(endpoints.items())
        ],
    }
    temp = path.with_suffix(path.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def _merge_edge_maps(
    target: dict[tuple[int, int, int, int], dict[str, Any]],
    source: dict[tuple[int, int, int, int], dict[str, Any]],
) -> None:
    for edge, row in source.items():
        existing = target.setdefault(edge, _new_edge_stat())
        existing["supportLegs"] += int(row.get("supportLegs", 0))
        existing["aircraft"].update(row.get("aircraft", set()))
        existing["callsigns"].update(row.get("callsigns", set()))
        existing["dates"].update(row.get("dates", set()))
        existing["aircraft"] = set(sorted(existing["aircraft"])[:MAX_EXAMPLES])
        existing["callsigns"] = set(sorted(existing["callsigns"])[:MAX_EXAMPLES])
        existing["dates"] = set(sorted(existing["dates"])[:MAX_EXAMPLES])


def _merge_chunk_edges(
    target: dict[tuple[int, int, int, int], dict[str, Any]],
    rows: list[dict[str, Any]],
) -> None:
    source: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    for row in rows:
        start = row.get("from", {})
        end = row.get("to", {})
        edge = (int(start.get("latCell", 0)), int(start.get("lonCell", 0)), int(end.get("latCell", 0)), int(end.get("lonCell", 0)))
        source[edge] = {
            "supportLegs": int(row.get("supportLegs", 0)),
            "aircraft": set(row.get("supportAircraftExamples", [])),
            "callsigns": set(row.get("supportCallsignExamples", [])),
            "dates": set(row.get("supportDates", [])),
        }
    _merge_edge_maps(target, source)


def _merge_endpoint_maps(
    target: dict[tuple[str, str], dict[str, Any]],
    source: dict[tuple[str, str], dict[str, Any]],
) -> None:
    for key, row in source.items():
        existing = target.setdefault(key, _new_endpoint_stat())
        existing["legs"] += int(row.get("legs", 0))
        existing["aircraft"].update(row.get("aircraft", set()))
        existing["callsigns"].update(row.get("callsigns", set()))
        existing["aircraft"] = set(sorted(existing["aircraft"])[:MAX_EXAMPLES])
        existing["callsigns"] = set(sorted(existing["callsigns"])[:MAX_EXAMPLES])


def _merge_chunk_endpoints(
    target: dict[tuple[str, str], dict[str, Any]],
    rows: list[dict[str, Any]],
) -> None:
    source: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("originIata") or ""), str(row.get("destinationIata") or ""))
        source[key] = {
            "legs": int(row.get("supportLegs", 0)),
            "aircraft": set(row.get("aircraftExamples", [])),
            "callsigns": set(row.get("callsignExamples", [])),
        }
    _merge_endpoint_maps(target, source)


def _nearest_cached(airport_index: AirportIndex, lat: float, lon: float, max_km: float, cache: dict[tuple[int, int], Any]) -> Any:
    key = (round(lat * 4), round(lon * 4))
    if key not in cache:
        cache[key] = airport_index.nearest(lat, lon, max_km)
    return cache[key]


def _quick_distance_km(previous: Any, current: Any) -> float:
    mean_lat = math.radians((previous.lat + current.lat) / 2.0)
    dx = (current.lon - previous.lon) * 111.320 * math.cos(mean_lat)
    dy = (current.lat - previous.lat) * 110.574
    return math.hypot(dx, dy)


def _split_legs_fast(points: list[Any], min_points: int, max_trace_gap_s: float) -> list[list[Any]]:
    legs: list[list[Any]] = []
    current: list[Any] = []
    previous = None
    for point in points:
        starts_new_leg = bool(point.flags & 2)
        gap_s = point.elapsed_s - previous.elapsed_s if previous is not None else 0
        too_sparse = previous is not None and gap_s > max_trace_gap_s
        jump_km = _quick_distance_km(previous, point) if previous is not None else 0
        jump_speed_kmh = jump_km / (gap_s / 3600) if gap_s > 0 else 0
        impossible_jump = previous is not None and gap_s <= 1200 and jump_speed_kmh > 1800
        if current and (starts_new_leg or too_sparse or impossible_jump):
            if len(current) >= min_points:
                legs.append(current)
            current = []
        current.append(point)
        previous = point
    if len(current) >= min_points:
        legs.append(current)
    return legs


def _write_progress(path: Path, date: str, stats: dict[str, int], elapsed: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updatedAt": datetime.now(timezone.utc).isoformat(), "date": date, "phase": "scan", "stats": stats, "wallSeconds": round(elapsed, 3)}
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
