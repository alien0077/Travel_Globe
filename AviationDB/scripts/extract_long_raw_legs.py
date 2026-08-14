#!/usr/bin/env python3
"""Extract only long raw ADS-B leg geometry for cross-region recovery.

The normal daily corridor artifact intentionally stores aggregated edges.  This
targeted pass preserves a compact sampled polyline for long legs so missing
airport endpoints or middle sections can be investigated without rebuilding a
large route pack.  It never reads IFR data and never writes runtime routes.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from process_raw_corridor_day import (  # noqa: E402
    HashingConcatenatedBinaryIO,
    _quick_distance_km,
    _split_legs_fast,
)

from aviationdb.observed_routes import (  # noqa: E402
    AirportIndex,
    _iter_trace_payloads_from_tarfile,
    haversine_km,
    parse_trace_points,
)

DEFAULT_AIRPORT_INDEX = ROOT / "shared/offline-packs/core-global/airports-index.json"
MAX_CHUNK_TRACES = 10_000


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract compact long-leg raw geometry for one ADS-B date.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--checkpoint-dir", type=Path, default=None)
    parser.add_argument("--progress", type=Path, default=None)
    parser.add_argument("--min-direct-km", type=float, default=3000.0)
    parser.add_argument("--min-points", type=int, default=8)
    parser.add_argument("--max-trace-gap-s", type=float, default=2700.0)
    parser.add_argument("--max-sample-points", type=int, default=96)
    parser.add_argument("--release-prefix", default=None, help="Exact release prefix before .tar.aa; defaults to prod, then staging.")
    args = parser.parse_args()

    parts, selected_prefix = _select_release_parts(args.raw_dir, args.release_prefix)
    if not parts or any(path.stat().st_size == 0 for path in parts):
        raise SystemExit(f"No complete raw split tar parts found in {args.raw_dir}")
    checkpoint_dir = args.checkpoint_dir or args.output.parent / f".{args.date}-long-leg-chunks"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    airport_index = AirportIndex.from_json(args.airport_index)
    chunks = sorted(checkpoint_dir.glob("chunk-*.json.gz"))
    resume_traces = sum(int(_read_gzip(path).get("stats", {}).get("tracesSeen", 0)) for path in chunks)
    stats = {
        "tracesSeen": sum(int(_read_gzip(path).get("stats", {}).get("tracesSeen", 0)) for path in chunks),
        "tracesParsed": sum(int(_read_gzip(path).get("stats", {}).get("tracesParsed", 0)) for path in chunks),
        "parseErrors": sum(int(_read_gzip(path).get("stats", {}).get("parseErrors", 0)) for path in chunks),
        "legsSeen": sum(int(_read_gzip(path).get("stats", {}).get("legsSeen", 0)) for path in chunks),
        "longLegs": sum(int(_read_gzip(path).get("stats", {}).get("longLegs", 0)) for path in chunks),
        "longLegsWithBothAirports": sum(
            int(_read_gzip(path).get("stats", {}).get("longLegsWithBothAirports", 0)) for path in chunks
        ),
    }
    long_legs: list[dict[str, Any]] = []
    source_files: set[str] = set()
    chunk_index = len(chunks) + 1
    traces_since_chunk = 0
    base_stats = stats.copy()
    started = time.monotonic()
    stream = HashingConcatenatedBinaryIO(parts)
    with stream, io.BufferedReader(stream, buffer_size=1024 * 1024) as buffered:
        for source_name, payload in _iter_trace_payloads_from_tarfile(
            buffered, label="+".join(path.name for path in parts[:2])
        ):
            raw_index = stats["tracesSeen"] + 1
            if raw_index <= resume_traces:
                continue
            stats["tracesSeen"] += 1
            traces_since_chunk += 1
            source_files.add(source_name.split(":", 1)[0])
            try:
                trace = json.loads(payload)
                points = parse_trace_points(trace)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                stats["parseErrors"] += 1
                continue
            stats["tracesParsed"] += 1
            icao = str(trace.get("icao") or "").strip().lower() or None
            for leg in _split_legs_fast(points, args.min_points, args.max_trace_gap_s):
                stats["legsSeen"] += 1
                direct_km = haversine_km(leg[0].lat, leg[0].lon, leg[-1].lat, leg[-1].lon)
                if direct_km < args.min_direct_km:
                    continue
                stats["longLegs"] += 1
                origin = airport_index.nearest(leg[0].lat, leg[0].lon, 500)
                destination = airport_index.nearest(leg[-1].lat, leg[-1].lon, 500)
                if origin is not None and destination is not None:
                    stats["longLegsWithBothAirports"] += 1
                long_legs.append(
                    _leg_record(
                        args.date,
                        source_name,
                        icao,
                        leg,
                        direct_km,
                        origin.airport.iata if origin else None,
                        destination.airport.iata if destination else None,
                        args.max_sample_points,
                    )
                )
            if args.progress and traces_since_chunk >= 1000:
                _write_progress(args.progress, args.date, stats, time.monotonic() - started)
            if traces_since_chunk >= MAX_CHUNK_TRACES:
                chunk_stats = {key: stats[key] - base_stats[key] for key in stats}
                _write_chunk(checkpoint_dir / f"chunk-{chunk_index:05d}.json.gz", chunk_stats, long_legs, source_files)
                chunk_index += 1
                base_stats = stats.copy()
                long_legs = []
                source_files = set()
                traces_since_chunk = 0

    final_legs: list[dict[str, Any]] = []
    final_sources: set[str] = set()
    for path in sorted(checkpoint_dir.glob("chunk-*.json.gz")):
        chunk = _read_gzip(path)
        final_legs.extend(chunk.get("longLegs", []))
        final_sources.update(str(value) for value in chunk.get("sourceFiles", []))
    final_legs.extend(long_legs)
    final_sources.update(source_files)
    payload = {
        "schemaVersion": 1,
        "evidenceType": "raw_derived_long_leg_geometry",
        "date": args.date,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "input": {
            "rawDir": str(args.raw_dir),
            "sourceFiles": sorted(final_sources),
            "combinedSha256": stream.hexdigest(),
            "releasePrefix": selected_prefix,
        },
        "method": {
            "minDirectKm": args.min_direct_km,
            "minPoints": args.min_points,
            "maxTraceGapS": args.max_trace_gap_s,
            "maxSamplePoints": args.max_sample_points,
            "ifrExcluded": True,
        },
        "stats": {**stats, "wallSeconds": round(time.monotonic() - started, 3)},
        "longLegs": final_legs,
    }
    _write_gzip_atomic(args.output, payload)
    if args.progress:
        _write_progress(args.progress, args.date, stats, time.monotonic() - started)
    print(json.dumps({"output": str(args.output), "stats": payload["stats"]}, ensure_ascii=False, indent=2))
    return 0


def _leg_record(
    date: str,
    source_name: str,
    icao: str | None,
    leg: list[Any],
    direct_km: float,
    origin_iata: str | None,
    destination_iata: str | None,
    max_sample_points: int,
) -> dict[str, Any]:
    route_km = sum(_quick_distance_km(left, right) for left, right in zip(leg, leg[1:], strict=False))
    sampled = _sample_points(leg, max_sample_points)
    callsigns = [point.callsign for point in leg if point.callsign]
    return {
        "date": date,
        "sourceFile": source_name,
        "icao": icao,
        "callsign": callsigns[0] if callsigns else None,
        "originIata": origin_iata,
        "destinationIata": destination_iata,
        "endpointStatus": (
            "both"
            if origin_iata and destination_iata
            else "partial"
            if origin_iata or destination_iata
            else "none"
        ),
        "first": {"lat": round(leg[0].lat, 5), "lon": round(leg[0].lon, 5), "elapsedS": leg[0].elapsed_s},
        "last": {"lat": round(leg[-1].lat, 5), "lon": round(leg[-1].lon, 5), "elapsedS": leg[-1].elapsed_s},
        "directKm": round(direct_km, 1),
        "routeKm": round(route_km, 1),
        "pointCount": len(leg),
        "sampledPoints": sampled,
        "geometryStatus": "observed_partial_leg",
    }


def _select_release_parts(raw_dir: Path, requested_prefix: str | None) -> tuple[list[Path], str]:
    suffixes = (".tar.aa", ".tar.ab", ".tar.ac", ".tar.ad", ".tar.ae", ".tar.af")
    files = [item for item in raw_dir.iterdir() if item.is_file() and item.name.endswith(suffixes)]
    groups: dict[str, list[Path]] = {}
    for path in files:
        prefix = path.name.rsplit(".tar.", 1)[0]
        groups.setdefault(prefix, []).append(path)
    if requested_prefix:
        selected = requested_prefix
    else:
        prod = sorted(prefix for prefix in groups if "-prod-" in prefix)
        staging = sorted(prefix for prefix in groups if "-staging-" in prefix)
        candidates = prod or staging or sorted(groups)
        if not candidates:
            raise SystemExit(f"No complete raw split tar parts found in {raw_dir}")
        selected = candidates[0]
    parts = sorted(groups.get(selected, []), key=lambda path: path.name)
    if not parts or any(path.stat().st_size == 0 for path in parts):
        raise SystemExit(f"No complete raw split tar parts found for prefix {selected} in {raw_dir}")
    return parts, selected


def _sample_points(leg: list[Any], max_points: int) -> list[dict[str, Any]]:
    if len(leg) <= max_points:
        indexes = range(len(leg))
    else:
        indexes = sorted({round(index * (len(leg) - 1) / (max_points - 1)) for index in range(max_points)})
    return [
        {
            "lat": round(leg[index].lat, 5),
            "lon": round(leg[index].lon, 5),
            "elapsedS": leg[index].elapsed_s,
            "altitudeFt": leg[index].altitude_ft,
            "trackDeg": leg[index].track_deg,
        }
        for index in indexes
    ]


def _write_chunk(path: Path, stats: dict[str, int], legs: list[dict[str, Any]], sources: set[str]) -> None:
    _write_gzip_atomic(path, {"stats": dict(stats), "longLegs": legs, "sourceFiles": sorted(sources)})


def _read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _write_gzip_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def _write_progress(path: Path, date: str, stats: dict[str, int], elapsed: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"date": date, "stats": stats, "wallSeconds": round(elapsed, 3)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
