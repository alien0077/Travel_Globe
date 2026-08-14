#!/usr/bin/env python3
"""Merge the seven immutable raw-derived daily corridor artifacts.

No IFR path, route-shape pack, or airport-pair validation output is read here.
The result is a provisional evidence graph; missing middle sections remain
unresolved instead of being straight-line filled.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
DATES = ["2026-08-02", "2026-08-01", "2026-07-31", "2026-07-30", "2026-07-29", "2026-07-28", "2026-07-27"]
CELL_DEG = 0.25
KHH = (22.577101, 120.349998)
NRT = (35.76858, 140.388714)


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge seven raw-derived corridor artifacts into a provisional global graph.")
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, default=PROJECT / "data/releases/private/observed-routes/adsblol/corridor-7d")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "data/releases/private/observed-routes/adsblol/corridor-7d/global")
    args = parser.parse_args()
    args.job_dir.mkdir(parents=True, exist_ok=True)
    args.output_root.mkdir(parents=True, exist_ok=True)
    db_path = args.job_dir / "corridor-merge.sqlite"
    manifest_path = args.job_dir / "merge-manifest.json"
    conn = _open_db(db_path)
    _write_status(args.job_dir, {"state": "running", "phase": "merge", "date": None})

    for date in DATES:
        input_path = args.input_root / date / "raw-derived-corridor.json.gz"
        if not input_path.exists():
            _write_status(args.job_dir, {"state": "blocked", "phase": "merge", "date": date, "reason": "missing_daily_output"})
            return 2
        if _is_done(conn, date):
            continue
        started = time.monotonic()
        with gzip.open(input_path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("evidenceType") != "raw_derived_unbiased":
            _write_status(args.job_dir, {"state": "blocked", "phase": "merge", "date": date, "reason": "non_raw_evidence_input"})
            return 3
        stats = payload.get("stats", {})
        if int(stats.get("parseErrors", 0)) != 0:
            _write_status(args.job_dir, {"state": "blocked", "phase": "merge", "date": date, "reason": "daily_parse_errors"})
            return 4
        conn.execute("BEGIN")
        for row in payload.get("corridorEdges", []):
            _merge_edge(conn, date, row)
        for row in payload.get("endpointCandidates", []):
            _merge_endpoint(conn, date, row)
        conn.execute("INSERT INTO processed_dates(date, input_bytes, input_sha256, wall_seconds) VALUES (?, ?, ?, ?)", (date, input_path.stat().st_size, str(payload.get("input", {}).get("combinedSha256") or ""), round(time.monotonic() - started, 3)))
        conn.commit()
        _write_status(args.job_dir, {"state": "running", "phase": "merge", "date": date, "dailyEdges": len(payload.get("corridorEdges", [])), "dailyWallSeconds": round(time.monotonic() - started, 3)})
        _write_manifest(manifest_path, conn)

    summary = _summarize(conn)
    khh_join = _analyze_khh_join(conn)
    outputs = _write_outputs(args.output_root, conn, summary, khh_join)
    qa = _qa(conn, summary, khh_join, outputs)
    (args.output_root / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_manifest(manifest_path, conn)
    _write_status(args.job_dir, {"state": "complete", "phase": "qa_complete", "summary": summary, "khhJoin": khh_join, "outputs": outputs})
    conn.close()
    return 0


def _open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS processed_dates (
            date TEXT PRIMARY KEY, input_bytes INTEGER NOT NULL, input_sha256 TEXT NOT NULL, wall_seconds REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS edges (
            edge_key TEXT PRIMARY KEY, from_lat INTEGER NOT NULL, from_lon INTEGER NOT NULL,
            to_lat INTEGER NOT NULL, to_lon INTEGER NOT NULL, support_legs INTEGER NOT NULL DEFAULT 0,
            aircraft_json TEXT NOT NULL DEFAULT '[]', callsigns_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS edge_dates (
            edge_key TEXT NOT NULL, date TEXT NOT NULL, PRIMARY KEY(edge_key, date)
        );
        CREATE TABLE IF NOT EXISTS endpoints (
            pair_key TEXT PRIMARY KEY, origin_iata TEXT NOT NULL, destination_iata TEXT NOT NULL,
            support_legs INTEGER NOT NULL DEFAULT 0, aircraft_json TEXT NOT NULL DEFAULT '[]', callsigns_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS endpoint_dates (
            pair_key TEXT NOT NULL, date TEXT NOT NULL, PRIMARY KEY(pair_key, date)
        );
        CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_lat, from_lon);
        CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_lat, to_lon);
        """
    )
    conn.commit()
    return conn


def _merge_edge(conn: sqlite3.Connection, date: str, row: dict[str, Any]) -> None:
    start = row.get("from", {})
    end = row.get("to", {})
    values = (int(start.get("latCell", 0)), int(start.get("lonCell", 0)), int(end.get("latCell", 0)), int(end.get("lonCell", 0)))
    key = ":".join(str(value) for value in values)
    aircraft = row.get("supportAircraftExamples", [])
    callsigns = row.get("supportCallsignExamples", [])
    existing = conn.execute("SELECT support_legs, aircraft_json, callsigns_json FROM edges WHERE edge_key = ?", (key,)).fetchone()
    if existing is None:
        conn.execute("INSERT INTO edges(edge_key, from_lat, from_lon, to_lat, to_lon, support_legs, aircraft_json, callsigns_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (key, *values, int(row.get("supportLegs", 0)), _json_examples(aircraft), _json_examples(callsigns)))
    else:
        merged_aircraft = _merge_examples(json.loads(existing[1]), aircraft)
        merged_callsigns = _merge_examples(json.loads(existing[2]), callsigns)
        conn.execute("UPDATE edges SET support_legs = ?, aircraft_json = ?, callsigns_json = ? WHERE edge_key = ?", (int(existing[0]) + int(row.get("supportLegs", 0)), json.dumps(merged_aircraft), json.dumps(merged_callsigns), key))
    conn.execute("INSERT OR IGNORE INTO edge_dates(edge_key, date) VALUES (?, ?)", (key, date))


def _merge_endpoint(conn: sqlite3.Connection, date: str, row: dict[str, Any]) -> None:
    origin = str(row.get("originIata") or "")
    destination = str(row.get("destinationIata") or "")
    key = f"{origin}:{destination}"
    aircraft = row.get("aircraftExamples", [])
    callsigns = row.get("callsignExamples", [])
    existing = conn.execute("SELECT support_legs, aircraft_json, callsigns_json FROM endpoints WHERE pair_key = ?", (key,)).fetchone()
    if existing is None:
        conn.execute("INSERT INTO endpoints(pair_key, origin_iata, destination_iata, support_legs, aircraft_json, callsigns_json) VALUES (?, ?, ?, ?, ?, ?)", (key, origin, destination, int(row.get("supportLegs", 0)), _json_examples(aircraft), _json_examples(callsigns)))
    else:
        conn.execute("UPDATE endpoints SET support_legs = ?, aircraft_json = ?, callsigns_json = ? WHERE pair_key = ?", (int(existing[0]) + int(row.get("supportLegs", 0)), json.dumps(_merge_examples(json.loads(existing[1]), aircraft)), json.dumps(_merge_examples(json.loads(existing[2]), callsigns)), key))
    conn.execute("INSERT OR IGNORE INTO endpoint_dates(pair_key, date) VALUES (?, ?)", (key, date))


def _summarize(conn: sqlite3.Connection) -> dict[str, Any]:
    dates = conn.execute("SELECT COUNT(*) FROM processed_dates").fetchone()[0]
    edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    supported = conn.execute("SELECT COUNT(*) FROM edges e WHERE (SELECT COUNT(*) FROM edge_dates d WHERE d.edge_key=e.edge_key) >= 2").fetchone()[0]
    stable = conn.execute("SELECT COUNT(*) FROM edges e WHERE (SELECT COUNT(*) FROM edge_dates d WHERE d.edge_key=e.edge_key) >= 3").fetchone()[0]
    endpoints = conn.execute("SELECT COUNT(*) FROM endpoints").fetchone()[0]
    return {"processedDates": dates, "totalDirectedEdges": edges, "supportedEdgesAtLeast2Dates": supported, "stableEdgesAtLeast3Dates": stable, "endpointPairs": endpoints, "classification": {"supported": "at least 2 independent dates; provisional", "stable": "at least 3 independent dates; provisional", "ifrExcluded": True}}


def _analyze_khh_join(conn: sqlite3.Connection) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in conn.execute("SELECT e.edge_key, e.from_lat, e.from_lon, e.to_lat, e.to_lon, e.support_legs, e.aircraft_json, COUNT(d.date) FROM edges e JOIN edge_dates d ON d.edge_key=e.edge_key GROUP BY e.edge_key HAVING COUNT(d.date) >= 2"):
        edge_key, from_lat, from_lon, to_lat, to_lon, legs, aircraft_json, support_days = row
        from_point = _cell_center(from_lat, from_lon)
        distance = _haversine(*KHH, *from_point)
        if distance <= 150:
            candidates.append({"edgeKey": edge_key, "distanceFromKhhKm": round(distance, 1), "supportDays": support_days, "supportLegs": legs, "aircraftExamples": json.loads(aircraft_json), "from": {"latCell": from_lat, "lonCell": from_lon}, "to": {"latCell": to_lat, "lonCell": to_lon}})
    candidates.sort(key=lambda item: (item["distanceFromKhhKm"], -item["supportDays"], -item["supportLegs"]))
    targets = []
    for row in conn.execute("SELECT e.edge_key, e.from_lat, e.from_lon, e.to_lat, e.to_lon, e.support_legs, COUNT(d.date) FROM edges e JOIN edge_dates d ON d.edge_key=e.edge_key GROUP BY e.edge_key HAVING COUNT(d.date) >= 2"):
        edge_key, from_lat, from_lon, to_lat, to_lon, legs, support_days = row
        distance = _haversine(*NRT, *_cell_center(to_lat, to_lon))
        if distance <= 150:
            targets.append({"edgeKey": edge_key, "distanceToNrtKm": round(distance, 1), "supportDays": support_days, "supportLegs": legs, "to": {"latCell": to_lat, "lonCell": to_lon}})
    targets.sort(key=lambda item: (item["distanceToNrtKm"], -item["supportDays"], -item["supportLegs"]))
    return {"interpretation": "corridor_inferred_only", "khhSupportedEntryEdgesWithin150Km": candidates[:100], "nrtSupportedExitEdgesWithin150Km": targets[:100], "pathFound": False, "middleGap": {"status": "unresolved_gap", "reason": "global graph merge does not invent an edge without raw support"}}


def _write_outputs(output_root: Path, conn: sqlite3.Connection, summary: dict[str, Any], khh_join: dict[str, Any]) -> dict[str, str]:
    graph_path = output_root / "global-corridor-graph.json.gz"
    evidence_path = output_root / "evidence-index.json.gz"
    _write_graph(graph_path, conn, summary, khh_join)
    with gzip.open(evidence_path, "wt", encoding="utf-8") as handle:
        json.dump({"schemaVersion": 1, "evidenceType": "raw_derived_unbiased", "summary": summary, "khhJoin": khh_join}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {"graph": str(graph_path), "evidenceIndex": str(evidence_path)}


def _write_graph(path: Path, conn: sqlite3.Connection, summary: dict[str, Any], khh_join: dict[str, Any]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write('{"schemaVersion":1,"evidenceType":"raw_derived_unbiased","graphType":"provisional_global_corridor","summary":')
        json.dump(summary, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write(',"khhJoin":')
        json.dump(khh_join, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write(',"edges":[')
        first = True
        for row in conn.execute("SELECT e.edge_key, e.from_lat, e.from_lon, e.to_lat, e.to_lon, e.support_legs, e.aircraft_json, e.callsigns_json, COUNT(d.date) FROM edges e JOIN edge_dates d ON d.edge_key=e.edge_key GROUP BY e.edge_key"):
            if not first:
                handle.write(",")
            first = False
            edge_key, from_lat, from_lon, to_lat, to_lon, legs, aircraft, callsigns, days = row
            json.dump({"edgeKey": edge_key, "from": {"latCell": from_lat, "lonCell": from_lon}, "to": {"latCell": to_lat, "lonCell": to_lon}, "supportDays": days, "supportLegs": legs, "aircraftExamples": json.loads(aircraft), "callsignExamples": json.loads(callsigns), "classification": "stable" if days >= 3 else "supported" if days >= 2 else "single_date_candidate"}, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write('],"endpoints":[')
        first = True
        for row in conn.execute("SELECT e.origin_iata, e.destination_iata, e.support_legs, e.aircraft_json, e.callsigns_json, COUNT(d.date) FROM endpoints e JOIN endpoint_dates d ON d.pair_key=e.pair_key GROUP BY e.pair_key"):
            if not first:
                handle.write(",")
            first = False
            origin, destination, legs, aircraft, callsigns, days = row
            json.dump({"originIata": origin, "destinationIata": destination, "supportDays": days, "supportLegs": legs, "aircraftExamples": json.loads(aircraft), "callsignExamples": json.loads(callsigns)}, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write(']}\n')


def _qa(conn: sqlite3.Connection, summary: dict[str, Any], khh_join: dict[str, Any], outputs: dict[str, str]) -> dict[str, Any]:
    return {"schemaVersion": 1, "generatedAt": datetime.now(timezone.utc).isoformat(), "passed": summary["processedDates"] == 7 and summary["totalDirectedEdges"] > 0 and khh_join["middleGap"]["status"] == "unresolved_gap", "checks": {"allSevenDatesMerged": summary["processedDates"] == 7, "hasGlobalEdges": summary["totalDirectedEdges"] > 0, "ifrExcluded": True, "noStraightLineMiddleFill": True, "khhStatus": khh_join["interpretation"]}, "outputs": outputs}


def _is_done(conn: sqlite3.Connection, date: str) -> bool:
    return conn.execute("SELECT 1 FROM processed_dates WHERE date = ?", (date,)).fetchone() is not None


def _merge_examples(existing: list[str], incoming: list[str], limit: int = 64) -> list[str]:
    values = list(dict.fromkeys([str(value) for value in existing + list(incoming) if value]))
    return sorted(values)[:limit]


def _json_examples(values: list[str]) -> str:
    return json.dumps(_merge_examples([], values), ensure_ascii=False)


def _cell_center(lat_cell: int, lon_cell: int) -> tuple[float, float]:
    return ((lat_cell * CELL_DEG) - 90 + CELL_DEG / 2, (lon_cell * CELL_DEG) - 180 + CELL_DEG / 2)


def _haversine(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = math.radians(b_lat - a_lat), math.radians(b_lon - a_lon)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1, math.sqrt(value)))


def _write_manifest(path: Path, conn: sqlite3.Connection) -> None:
    rows = [dict(date=row[0], bytes=row[1], sha256=row[2], wallSeconds=row[3]) for row in conn.execute("SELECT date, input_bytes, input_sha256, wall_seconds FROM processed_dates ORDER BY date DESC")]
    path.write_text(json.dumps({"schemaVersion": 1, "processedDates": rows, "updatedAt": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_status(job_dir: Path, payload: dict[str, Any]) -> None:
    path = job_dir / "merge-status.json"
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({"updatedAt": datetime.now(timezone.utc).isoformat(), **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
