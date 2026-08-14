#!/usr/bin/env python3
"""Add raw long-leg geometry as a non-duplicating supplemental graph layer.

The daily corridor graph is the primary raw-derived graph.  This stage only
uses the compact long-leg artifacts to recover local cell-to-cell geometry
that the daily aggregation did not retain.  It never adds support to an
existing edge, never reads IFR data, and refuses to bridge sampled gaps longer
than the local evidence limit.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import shutil
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CELL_DEG = 0.25
MAX_LOCAL_SEGMENT_KM = 180.0
MAX_EDGE_JUMP_CELLS = 4
DATES = (
    "2026-08-02", "2026-08-01", "2026-07-31", "2026-07-30",
    "2026-07-29", "2026-07-28", "2026-07-27",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a supplemental graph from retained raw long-leg geometry.")
    parser.add_argument("--long-legs-root", type=Path, default=Path("/private/tmp/travel-globe-long-legs-7d"))
    parser.add_argument(
        "--base-db", type=Path,
        default=Path("/private/tmp/travel-globe-corridor-7d/corridor-merge.sqlite"),
    )
    parser.add_argument(
        "--output-db", type=Path,
        default=Path("/private/tmp/travel-globe-corridor-7d/corridor-merge-long-legs.sqlite"),
    )
    parser.add_argument(
        "--report", type=Path,
        default=Path("/private/tmp/travel-globe-corridor-7d/long-leg-supplement.json"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    args.long_legs_root = args.long_legs_root.expanduser().resolve()
    args.base_db = args.base_db.expanduser().resolve()
    args.output_db = args.output_db.expanduser().resolve()
    args.report = args.report.expanduser().resolve()

    if not args.base_db.exists():
        raise SystemExit(f"Missing base database: {args.base_db}")
    inputs = [args.long_legs_root / date / "raw-long-legs.json.gz" for date in DATES]
    missing = [str(path) for path in inputs if not path.exists()]
    if missing:
        raise SystemExit(f"Missing long-leg outputs: {', '.join(missing)}")

    if args.output_db.exists() and args.report.exists() and not args.force:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if report.get("schemaVersion") == 1 and report.get("input", {}).get("dates") == list(DATES):
            print(json.dumps(
                {"state": "reused", "outputDb": str(args.output_db), "report": str(args.report)},
                ensure_ascii=False, indent=2,
            ))
            return 0

    args.output_db.parent.mkdir(parents=True, exist_ok=True)
    if args.output_db.exists():
        args.output_db.unlink()
    shutil.copy2(args.base_db, args.output_db)

    existing_edges = _load_existing_edges(args.output_db)
    edge_records: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    airport_pairs: dict[tuple[str, str], dict[str, Any]] = {}
    stats = defaultdict(int)
    for date, path in zip(DATES, inputs, strict=True):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        stats["longLegsRead"] += len(payload.get("longLegs", []))
        stats["sourceDates"] += 1
        for leg in payload.get("longLegs", []):
            stats["legsConsidered"] += 1
            _record_airport_pair(airport_pairs, date, leg)
            points = leg.get("sampledPoints", [])
            if len(points) < 2:
                stats["legsTooShortForGeometry"] += 1
                continue
            leg_edges = _sampled_edges(points, stats)
            if not leg_edges:
                stats["legsWithoutLocalEdges"] += 1
                continue
            stats["legsWithLocalEdges"] += 1
            seen_in_leg: set[tuple[int, int, int, int]] = set()
            for edge in leg_edges:
                if edge in seen_in_leg:
                    continue
                seen_in_leg.add(edge)
                row = edge_records.setdefault(edge, _new_edge_record())
                row["supportLegKeys"].add(f"{date}:{leg.get('icao') or ''}:{leg.get('sourceFile') or ''}")
                row["dates"].add(date)
                if leg.get("icao"):
                    row["aircraft"].add(str(leg["icao"]))
                if leg.get("callsign"):
                    row["callsigns"].add(str(leg["callsign"]))

    connection = sqlite3.connect(args.output_db)
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS supplemental_edge_sources (
            edge_key TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            support_legs INTEGER NOT NULL,
            support_dates_json TEXT NOT NULL,
            aircraft_json TEXT NOT NULL,
            callsigns_json TEXT NOT NULL
        )
        """
    )
    inserted = 0
    skipped_existing = 0
    skipped_single_date = 0
    for edge, row in sorted(edge_records.items()):
        if edge in existing_edges:
            skipped_existing += 1
            continue
        if len(row["dates"]) < 2:
            skipped_single_date += 1
            continue
        key = ":".join(str(value) for value in edge)
        aircraft = sorted(row["aircraft"])[:64]
        callsigns = sorted(row["callsigns"])[:64]
        dates = sorted(row["dates"])
        support_legs = len(row["supportLegKeys"])
        connection.execute(
            "INSERT OR IGNORE INTO edges(edge_key, from_lat, from_lon, to_lat, to_lon, "
            "support_legs, aircraft_json, callsigns_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (key, *edge, support_legs, json.dumps(aircraft), json.dumps(callsigns)),
        )
        for date in dates:
            connection.execute("INSERT OR IGNORE INTO edge_dates(edge_key, date) VALUES (?, ?)", (key, date))
        connection.execute(
            "INSERT OR REPLACE INTO supplemental_edge_sources("
            "edge_key, source_type, support_legs, support_dates_json, aircraft_json, callsigns_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                key, "raw_long_leg_geometry", support_legs, json.dumps(dates),
                json.dumps(aircraft), json.dumps(callsigns),
            ),
        )
        inserted += 1
    connection.commit()
    connection.close()

    report = {
        "schemaVersion": 1,
        "evidenceType": "raw_derived_long_leg_supplement",
        "generatedAt": datetime.now(UTC).isoformat(),
        "input": {
            "dates": list(DATES),
            "longLegsRoot": str(args.long_legs_root),
            "baseDb": str(args.base_db),
            "ifrExcluded": True,
            "baseEdgesPreserved": True,
        },
        "method": {
            "cellDegrees": CELL_DEG,
            "maxLocalSegmentKm": MAX_LOCAL_SEGMENT_KM,
            "maxEdgeJumpCells": MAX_EDGE_JUMP_CELLS,
            "minSupportDatesForSupplement": 2,
            "noSupportAddedToExistingEdges": True,
            "noLongStraightLineFill": True,
        },
        "stats": {
            **dict(stats),
            "candidateEdges": len(edge_records),
            "insertedSupplementalEdges": inserted,
            "skippedExistingEdges": skipped_existing,
            "skippedSingleDateEdges": skipped_single_date,
            "airportPairEvidence": len(airport_pairs),
            "khhAirportPairEvidence": sum(1 for pair in airport_pairs if "KHH" in pair),
        },
        "airportPairs": _serialize_pairs(airport_pairs),
        "outputDb": str(args.output_db),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(
        {"state": "complete", "outputDb": str(args.output_db), "report": str(args.report), "stats": report["stats"]},
        ensure_ascii=False, indent=2,
    ))
    return 0


def _load_existing_edges(path: Path) -> set[tuple[int, int, int, int]]:
    connection = sqlite3.connect(path)
    rows = connection.execute("SELECT from_lat, from_lon, to_lat, to_lon FROM edges")
    result = {tuple(int(value) for value in row) for row in rows}
    connection.close()
    return result


def _new_edge_record() -> dict[str, Any]:
    return {"supportLegKeys": set(), "dates": set(), "aircraft": set(), "callsigns": set()}


def _record_airport_pair(target: dict[tuple[str, str], dict[str, Any]], date: str, leg: dict[str, Any]) -> None:
    origin = str(leg.get("originIata") or "").upper()
    destination = str(leg.get("destinationIata") or "").upper()
    if not origin or not destination or origin == destination:
        return
    key = (origin, destination)
    row = target.setdefault(key, {"dates": set(), "aircraft": set(), "callsigns": set(), "legs": 0})
    row["dates"].add(date)
    row["legs"] += 1
    if leg.get("icao"):
        row["aircraft"].add(str(leg["icao"]))
    if leg.get("callsign"):
        row["callsigns"].add(str(leg["callsign"]))


def _sampled_edges(points: list[dict[str, Any]], stats: defaultdict[str, int]) -> set[tuple[int, int, int, int]]:
    edges: set[tuple[int, int, int, int]] = set()
    for left, right in zip(points, points[1:], strict=False):
        start = (float(left["lat"]), float(left["lon"]))
        end = (float(right["lat"]), float(right["lon"]))
        distance = _haversine_km(start, end)
        if distance > MAX_LOCAL_SEGMENT_KM:
            stats["sampledGapsOverLimit"] = stats.get("sampledGapsOverLimit", 0) + 1
            continue
        start_cell = _cell(*start)
        end_cell = _cell(*end)
        cells = _walk_cells(start_cell, end_cell)
        for previous, current in zip(cells, cells[1:], strict=False):
            if previous != current:
                lat_delta = abs(current[0] - previous[0])
                lon_delta = abs(current[1] - previous[1])
                if lat_delta <= MAX_EDGE_JUMP_CELLS and lon_delta <= MAX_EDGE_JUMP_CELLS:
                    edges.add((*previous, *current))
    return edges


def _walk_cells(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    steps = max(abs(end[0] - start[0]), abs(end[1] - start[1]), 1)
    cells = []
    for index in range(steps + 1):
        ratio = index / steps
        cell = (round(start[0] + (end[0] - start[0]) * ratio), round(start[1] + (end[1] - start[1]) * ratio))
        if not cells or cell != cells[-1]:
            cells.append(cell)
    return cells


def _cell(lat: float, lon: float) -> tuple[int, int]:
    return math.floor((lat + 90.0) / CELL_DEG), math.floor((lon + 180.0) / CELL_DEG)


def _haversine_km(left: tuple[float, float], right: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, left)
    lat2, lon2 = map(math.radians, right)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def _serialize_pairs(pairs: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for (origin, destination), row in sorted(pairs.items()):
        output.append(
            {
                "originIata": origin,
                "destinationIata": destination,
                "supportDays": len(row["dates"]),
                "supportLegs": row["legs"],
                "aircraftCount": len(row["aircraft"]),
                "callsignCount": len(row["callsigns"]),
                "dates": sorted(row["dates"]),
                "aircraftExamples": sorted(row["aircraft"])[:24],
                "callsignExamples": sorted(row["callsigns"])[:24],
            }
        )
    return output


if __name__ == "__main__":
    raise SystemExit(main())
