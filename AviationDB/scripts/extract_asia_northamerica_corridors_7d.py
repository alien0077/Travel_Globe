#!/usr/bin/env python3
"""Find Asia/Southeast-Asia <-> North-America flights from raw geometry.

This deliberately uses geographic basin gates instead of nearest-airport
labels.  It retains qualifying flight segments and aggregates their observed
1-degree directed cells into a trans-Pacific shared-corridor candidate graph.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from process_raw_corridor_day import HashingConcatenatedBinaryIO, _split_legs_fast
from aviationdb.observed_routes import _iter_trace_payloads_from_tarfile, parse_trace_points

DATES = ["2026-08-02", "2026-08-01", "2026-07-31", "2026-07-30", "2026-07-29", "2026-07-28", "2026-07-27"]
ASIA_BOXES = (
    (-10.0, 25.0, 90.0, 145.0),
    (20.0, 60.0, 100.0, 155.0),
)
NORTH_AMERICA = (15.0, 72.0, -180.0, -50.0)
CELL_DEG = 1.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    _status(args.status, {"state": "running", "phase": "preflight", "dates": DATES})
    for date in DATES:
        output = args.output_root / f"{date}.json.gz"
        if output.exists() and _valid(output, date):
            continue
        _process_date(date, args.raw_root / date, output, args.status)
    _aggregate(args.output_root, args.status)
    _status(args.status, {"state": "complete", "phase": "written", "dates": DATES})
    return 0


def _process_date(date: str, raw_dir: Path, output: Path, status: Path) -> None:
    parts = sorted(p for p in raw_dir.iterdir() if p.is_file() and p.name.endswith((".tar.aa", ".tar.ab", ".tar.ac", ".tar.ad", ".tar.ae", ".tar.af")))
    if not parts:
        raise SystemExit(f"missing raw parts: {date}")
    tracks: list[dict[str, Any]] = []
    stats = {"tracesSeen": 0, "tracesParsed": 0, "parseErrors": 0, "legsSeen": 0, "candidateSegments": 0}
    started = time.monotonic()
    stream = HashingConcatenatedBinaryIO(parts)
    with stream, io.BufferedReader(stream, buffer_size=1024 * 1024) as buffered:
        for source, payload in _iter_trace_payloads_from_tarfile(buffered, label="+".join(p.name for p in parts[:2])):
            stats["tracesSeen"] += 1
            try:
                trace = json.loads(payload)
                points = parse_trace_points(trace)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                stats["parseErrors"] += 1
                continue
            stats["tracesParsed"] += 1
            icao = str(trace.get("icao") or "").strip().lower() or None
            # 跨洋 ADS-B 會有長時間無地面接收站；不能用一般陸地航段
            # 的 45 分鐘缺測門檻，否則北太平洋中段會被先切斷。
            for leg in _split_legs_fast(points, 8, 21600):
                stats["legsSeen"] += 1
                for callsign, segment in _callsign_segments(leg):
                    match = _gate_match(segment)
                    if not match:
                        continue
                    stats["candidateSegments"] += 1
                    tracks.append(_track(date, source, icao, callsign, segment, match))
            if stats["tracesSeen"] % 10000 == 0:
                _status(status, {"state": "running", "phase": "scan", "date": date, "stats": stats, "wallSeconds": round(time.monotonic() - started, 1)})
    _write_gzip(output, {"schemaVersion": 2, "evidenceType": "raw_derived_asia_northamerica_flights_v2", "date": date, "stats": stats, "tracks": tracks})
    _status(status, {"state": "running", "phase": "date_complete", "date": date, "stats": stats, "wallSeconds": round(time.monotonic() - started, 1)})


def _callsign_segments(points: list[Any]) -> list[tuple[str, list[Any]]]:
    # 海上接收不完整時 callsign 會在 trace 中間缺值；leg 已由起飛旗標、
    # 長缺測與不可能跳點切開，幾何判定必須保留完整 leg。
    values = [str(point.callsign or "").strip().upper() for point in points]
    counts = Counter(value for value in values if value)
    callsign = counts.most_common(1)[0][0] if counts else "UNKNOWN"
    return [(callsign, points)] if len(points) >= 8 else []


def _gate_match(points: list[Any]) -> dict[str, Any] | None:
    asia = [_in_any_box(p.lat, p.lon, ASIA_BOXES) for p in points]
    na = [_in_box(p.lat, p.lon, NORTH_AMERICA) for p in points]
    if not any(asia) or not any(na):
        return None
    ai = next(i for i, value in enumerate(asia) if value)
    ni = next(i for i, value in enumerate(na) if value)
    if ai == ni:
        return None
    direction = "Asia-NorthAmerica" if ai < ni else "NorthAmerica-Asia"
    first, last = (ai, ni) if ai < ni else (ni, ai)
    if _rough_distance(points[first], points[last]) < 4000:
        return None
    return {"direction": direction, "asiaIndex": ai, "northAmericaIndex": ni, "gateSpanKm": round(_rough_distance(points[first], points[last]), 1)}


def _track(date: str, source: str, icao: str | None, callsign: str, points: list[Any], match: dict[str, Any]) -> dict[str, Any]:
    flight_id = f"{date}:{icao or 'unknown'}:{callsign}:{source.split(':', 1)[0]}"
    sampled = _sample(points, 96)
    return {"flightId": flight_id, "date": date, "icao": icao, "callsign": callsign, "sourceFile": source, "direction": match["direction"], "gateSpanKm": match["gateSpanKm"], "pointCount": len(points), "sampledPoints": sampled, "observedEdges": _edges(points)}


def _edges(points: list[Any]) -> list[list[int]]:
    result: list[list[int]] = []
    seen: set[tuple[int, int, int, int]] = set()
    previous = None
    for point in points:
        cell = (math_floor((point.lat + 90) / CELL_DEG), math_floor((point.lon + 180) / CELL_DEG))
        if previous and cell != previous and abs(cell[0] - previous[0]) <= 4 and abs(cell[1] - previous[1]) <= 4:
            edge = (*previous, *cell)
            if edge not in seen:
                seen.add(edge)
                result.append(list(edge))
        previous = cell
    return result


def _aggregate(root: Path, status: Path) -> None:
    flights: list[dict[str, Any]] = []
    support: dict[tuple[int, int, int, int], dict[str, set[str]]] = defaultdict(lambda: {"dates": set(), "flights": set()})
    for path in sorted(root.glob("2026-*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        for track in payload.get("tracks", []):
            flights.append({key: value for key, value in track.items() if key != "observedEdges"})
            for edge in track.get("observedEdges", []):
                row = support[tuple(edge)]
                row["dates"].add(track["date"])
                row["flights"].add(track["flightId"])
    edges = []
    for edge, row in support.items():
        edges.append({"from": {"latCell": edge[0], "lonCell": edge[1]}, "to": {"latCell": edge[2], "lonCell": edge[3]}, "supportDates": sorted(row["dates"]), "supportFlightCount": len(row["flights"]), "classification": "shared_observed" if len(row["dates"]) >= 2 and len(row["flights"]) >= 3 else "single_or_weak_observed"})
    summary = {"candidateFlights": len(flights), "asiaToNorthAmerica": sum(f["direction"] == "Asia-NorthAmerica" for f in flights), "northAmericaToAsia": sum(f["direction"] == "NorthAmerica-Asia" for f in flights), "sharedEdges": sum(e["classification"] == "shared_observed" for e in edges), "totalObservedEdges": len(edges), "airportEndpointsUsed": False, "ifrUsed": False}
    _write_gzip(root / "asia-northamerica-corridor.json.gz", {"schemaVersion": 2, "evidenceType": "raw_derived_asia_northamerica_shared_corridor_v2", "generatedAt": datetime.now(timezone.utc).isoformat(), "summary": summary, "flights": flights, "edges": edges, "limitations": ["candidate flight is gate-qualified, not airport-endpoint-qualified", "shared corridor requires repeated dates and flights", "no missing middle is invented"]})
    _status(status, {"state": "running", "phase": "aggregate_complete", "summary": summary})


def _in_box(lat: float, lon: float, box: tuple[float, float, float, float]) -> bool:
    return box[0] <= lat <= box[1] and box[2] <= lon <= box[3]


def _in_any_box(lat: float, lon: float, boxes: tuple[tuple[float, float, float, float], ...]) -> bool:
    return any(_in_box(lat, lon, box) for box in boxes)


def _rough_distance(a: Any, b: Any) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(((b.lon - a.lon + 180.0) % 360.0) - 180.0)
    haversine = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return 6371.0088 * 2.0 * math.asin(min(1.0, math.sqrt(haversine)))


def _sample(points: list[Any], limit: int) -> list[dict[str, Any]]:
    indexes = range(len(points)) if len(points) <= limit else sorted({round(i * (len(points) - 1) / (limit - 1)) for i in range(limit)})
    return [{"lat": round(points[i].lat, 5), "lon": round(points[i].lon, 5), "elapsedS": points[i].elapsed_s, "trackDeg": points[i].track_deg} for i in indexes]


def math_floor(value: float) -> int:
    return int(value // 1)


def _write_gzip(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def _valid(path: Path, date: str) -> bool:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle: payload = json.load(handle)
        return payload.get("date") == date and payload.get("evidenceType") == "raw_derived_asia_northamerica_flights_v2"
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({"updatedAt": datetime.now(timezone.utc).isoformat(), **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
