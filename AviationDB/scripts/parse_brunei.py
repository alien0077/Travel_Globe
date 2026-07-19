#!/usr/bin/env python3
"""
汶萊 AIP PDF Parser - 解析汶萊 DCA AIP PDF 為 SQLite

從汶萊 ENR 3.1 PDF 萃取 ATS Routes。汶萊航路資料量小（約 5 條航線）。
PDF 表格結構在文字萃取後會散失，此腳本使用正規表示式模式比對。

用法：
  python scripts/parse_brunei.py --dir data/raw/brunei/2026-06-20
  python scripts/parse_brunei.py --dir data/raw/brunei/2026-06-20 --db data/processed/aviation-bn.sqlite
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import asin, atan2, cos, degrees, radians, sin, sqrt
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 共用工具
# ---------------------------------------------------------------------------

EARTH_RADIUS_NM = 3440.065


class CoordinateParseError(ValueError):
    pass


def parse_coordinate(text: str) -> float:
    value = text.strip().upper().replace(" ", "")
    match = re.fullmatch(r"([NSEW])?(\d+(?:\.\d+)?)([NSEW])?", value)
    if not match:
        raise CoordinateParseError(f"Cannot parse: {text}")
    hemisphere = match.group(1) or match.group(3)
    if hemisphere is None:
        raise CoordinateParseError(f"Missing hemisphere: {text}")
    digits = match.group(2)
    is_lon = hemisphere in {"E", "W"}
    degree_digits = 3 if is_lon else 2
    if len(digits.split(".")[0]) < degree_digits + 4:
        raise CoordinateParseError(f"Too short: {text}")
    d = int(digits[:degree_digits])
    m = int(digits[degree_digits : degree_digits + 2])
    s = float(digits[degree_digits + 2 :])
    decimal = d + m / 60 + s / 3600
    if hemisphere in {"S", "W"}:
        decimal *= -1
    return decimal


_COORD_RE = re.compile(r"(\d{6}(?:\.\d+)?[NS])\s*(\d{7}(?:\.\d+)?[EW])", re.IGNORECASE)


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_NM * asin(sqrt(a))


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    y = sin(dlon) * cos(lat2)
    x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)
    return (atan2(y, x) * 180 / 3.141592653589793 + 360) % 360


def normalize_ident(value: str) -> str:
    return " ".join(value.strip().upper().split())


# ---------------------------------------------------------------------------
# 資料模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NavPoint:
    uid: str
    ident: str
    latitude: float
    longitude: float
    point_type: str
    source_id: str
    country: str | None = "BN"
    fir: str | None = "KOTA_KINABALU"
    region_code: str | None = "asia-southeast"


@dataclass(frozen=True)
class Airway:
    uid: str
    designator: str
    route_type: str | None
    country: str
    fir: str
    source_id: str


@dataclass(frozen=True)
class AirwaySegment:
    uid: str
    airway_uid: str
    sequence: int
    from_point_uid: str
    to_point_uid: str
    distance_nm: float | None
    initial_course_deg: float | None
    reverse_course_deg: float | None
    source_id: str


@dataclass
class ParsedDataset:
    points: list[NavPoint] = field(default_factory=list)
    airways: list[Airway] = field(default_factory=list)
    segments: list[AirwaySegment] = field(default_factory=list)
    issues: list[dict[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# UID
# ---------------------------------------------------------------------------


def _suid(prefix: str, *parts: object) -> str:
    from hashlib import sha256

    return f"{prefix}-{sha256('|'.join('' if p is None else str(p) for p in parts).encode()).hexdigest()[:16]}"


def _puid(ident: str, lat: float, lon: float) -> str:
    return _suid("pt", normalize_ident(ident), f"{lat:.6f}", f"{lon:.6f}", "KOTA_KINABALU")


def _auid(designator: str, source_id: str) -> str:
    return _suid("awy", normalize_ident(designator), source_id, "KOTA_KINABALU")


def _suid_seg(awy_id: str, seq: int, f_uid: str, t_uid: str) -> str:
    return _suid("seg", awy_id, seq, f_uid, t_uid)


# ---------------------------------------------------------------------------
# PDF 文字萃取
# ---------------------------------------------------------------------------


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from PDF using pypdf."""
    from pypdf import PdfReader

    r = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() for page in r.pages)


# ---------------------------------------------------------------------------
# Brunei ENR 3.1 Parser (PDF text based)
# ---------------------------------------------------------------------------


def parse_brunei_enr31(text: str, source_id: str, dataset: ParsedDataset) -> None:
    """Parse Brunei ENR 3.1 from PDF text. Small dataset (~5 routes)."""
    point_by_ident: dict[str, NavPoint] = {}

    # Find all route blocks - each starts with a route designator line
    # Route designators look like: "L649 (RNP10)" or "M646 (RNP 10)" or "M522"
    route_blocks = re.split(r"\n\s*(?=[A-Z]\d{1,4}\s*(?:\([^)]*\))?\s*\n)", text)

    for block in route_blocks:
        block = block.strip()
        if not block:
            continue

        # Extract route designator
        designator_match = re.match(r"([A-Z]\d{1,4}[A-Z]?)\s*(?:\(([^)]*)\))?", block)
        if not designator_match:
            continue

        designator = normalize_ident(designator_match.group(1))
        route_type = normalize_ident(designator_match.group(2) or "ATS")

        # Extract all points with coordinates
        route_points: list[NavPoint] = []

        for m in _COORD_RE.finditer(block):
            lat_str, lon_str = m.groups()
            try:
                lat = parse_coordinate(lat_str)
                lon = parse_coordinate(lon_str)
            except CoordinateParseError:
                continue

            # Get ident - text before coordinate on the same line
            before = block[: m.start()].strip().split("\n")
            id_line = before[-1] if before else ""

            # Try to extract ident
            ident = ""
            # Check for navaid pattern: "BRUNEI DVOR/DME (BRU)" or "KOTA KINABALU DVOR/DME (VJN)"
            navaid_m = re.search(r"\(([A-Z0-9]{2,5})\)\s*$", id_line)
            if navaid_m:
                ident = navaid_m.group(1)
            else:
                # Use the last word before coord
                tokens = id_line.strip().split()
                if tokens:
                    candidate = tokens[-1].strip("()")
                    if re.match(r"^[A-Z0-9]{3,6}$", candidate):
                        ident = candidate

            if not ident:
                continue

            ident = normalize_ident(ident)
            is_navaid = "DVOR" in id_line or "DME" in id_line or "VOR" in id_line or "NDB" in id_line

            pt = NavPoint(
                uid=_puid(ident, lat, lon),
                ident=ident,
                latitude=lat,
                longitude=lon,
                point_type="NAVAID" if is_navaid else "SIGNIFICANT_POINT",
                source_id=source_id,
            )

            stored = point_by_ident.get(ident)
            if stored is None:
                point_by_ident[ident] = pt
                dataset.points.append(pt)
                stored = pt

            route_points.append(stored)

        if len(route_points) < 2:
            dataset.issues.append({
                "severity": "warning", "code": "bn-route-too-short",
                "message": f"{designator}: only {len(route_points)} points",
            })
            continue

        airway = Airway(
            uid=_auid(designator, source_id),
            designator=designator,
            route_type=route_type,
            country="BN",
            fir="KOTA_KINABALU",
            source_id=source_id,
        )
        dataset.airways.append(airway)

        # Create segments
        for i in range(1, len(route_points)):
            prev = route_points[i - 1]
            curr = route_points[i]
            dist = haversine_nm(prev.latitude, prev.longitude, curr.latitude, curr.longitude)
            course = initial_bearing(prev.latitude, prev.longitude, curr.latitude, curr.longitude)

            dataset.segments.append(
                AirwaySegment(
                    uid=_suid_seg(airway.uid, i, prev.uid, curr.uid),
                    airway_uid=airway.uid,
                    sequence=i,
                    from_point_uid=prev.uid,
                    to_point_uid=curr.uid,
                    distance_nm=round(dist, 2),
                    initial_course_deg=round(course, 1),
                    reverse_course_deg=round((course + 180) % 360, 1),
                    source_id=source_id,
                )
            )


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_metadata (
    source_id TEXT PRIMARY KEY, provider TEXT NOT NULL, country TEXT,
    source_url TEXT NOT NULL, source_type TEXT NOT NULL, airac_cycle TEXT,
    effective_date TEXT, retrieved_at TEXT NOT NULL, raw_file_sha256 TEXT NOT NULL,
    license_url TEXT, redistribution_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nav_point (
    uid TEXT PRIMARY KEY, ident TEXT NOT NULL, name TEXT,
    latitude REAL NOT NULL, longitude REAL NOT NULL,
    point_type TEXT NOT NULL, usage_type TEXT, country TEXT, fir TEXT,
    region_code TEXT, source_id TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS airway (
    uid TEXT PRIMARY KEY, designator TEXT NOT NULL, route_type TEXT,
    country TEXT, fir TEXT, source_id TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS airway_segment (
    uid TEXT PRIMARY KEY, airway_uid TEXT NOT NULL, sequence INTEGER NOT NULL,
    from_point_uid TEXT NOT NULL, to_point_uid TEXT NOT NULL,
    distance_nm REAL, initial_course_deg REAL, reverse_course_deg REAL,
    source_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_np_ident ON nav_point(ident);
CREATE INDEX IF NOT EXISTS idx_awy_desig ON airway(designator);
CREATE INDEX IF NOT EXISTS idx_seg_awy ON airway_segment(airway_uid, sequence);
"""


def _create_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _insert_dataset(conn: sqlite3.Connection, ds: ParsedDataset, source_id: str, cycle: str) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO source_metadata VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (source_id, "Department of Civil Aviation Brunei Darussalam", "BN",
         "https://www.dca.gov.bn/eaip/", "aip_pdf", cycle, cycle,
         datetime.now(UTC).isoformat(), "manual", None, "manual_review_required"),
    )
    for pt in ds.points:
        conn.execute(
            "INSERT OR REPLACE INTO nav_point VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
            (pt.uid, pt.ident, pt.ident, pt.latitude, pt.longitude, pt.point_type,
             "ENROUTE", pt.country, pt.fir, pt.region_code, pt.source_id),
        )
    for awy in ds.airways:
        conn.execute(
            "INSERT OR REPLACE INTO airway VALUES (?,?,?,?,?,?,1)",
            (awy.uid, awy.designator, awy.route_type, awy.country, awy.fir, awy.source_id),
        )
    for seg in ds.segments:
        conn.execute(
            "INSERT OR REPLACE INTO airway_segment VALUES (?,?,?,?,?,?,?,?,?)",
            (seg.uid, seg.airway_uid, seg.sequence, seg.from_point_uid, seg.to_point_uid,
             seg.distance_nm, seg.initial_course_deg, seg.reverse_course_deg, seg.source_id),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Parse Brunei AIP PDF into SQLite")
    parser.add_argument("--dir", required=True, help="Raw data directory (e.g. data/raw/brunei/2026-06-20)")
    parser.add_argument("--db", default=None, help="Output SQLite path")
    parser.add_argument("--source-id", default="brunei", help="Source identifier")
    args = parser.parse_args()

    raw_dir = Path(args.dir)
    if not raw_dir.is_dir():
        print(f"✗ Directory not found: {raw_dir}")
        sys.exit(1)

    project_root = Path(__file__).resolve().parent.parent
    db_path = Path(args.db) if args.db else project_root / "data" / "processed" / "aviation-bn.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # 找 ENR 3.1 PDF
    enr31_pdf = raw_dir / "ENR-3.1.pdf"
    if not enr31_pdf.exists():
        print(f"✗ ENR-3.1.pdf not found in {raw_dir}")
        sys.exit(1)

    print(f"Parsing Brunei AIP...")
    print(f"  Source: {enr31_pdf}")
    print(f"  Output: {db_path}\n")

    # Extract PDF text
    pdf_text = extract_pdf_text(enr31_pdf)
    print(f"  PDF text: {len(pdf_text)} chars")

    # Parse
    dataset = ParsedDataset()
    parse_brunei_enr31(pdf_text, args.source_id, dataset)

    print(f"\nResults:")
    print(f"  NavPoints: {len(dataset.points)}")
    print(f"  Airways:   {len(dataset.airways)}")
    print(f"  Segments:  {len(dataset.segments)}")
    print(f"  Issues:    {len(dataset.issues)}")

    for awy in dataset.airways:
        segs = [s for s in dataset.segments if s.airway_uid == awy.uid]
        print(f"    {awy.designator}: {len(segs)} segments")

    print(f"\nWriting to SQLite...")
    conn = _create_db(db_path)
    _insert_dataset(conn, dataset, args.source_id, raw_dir.name)

    c = conn.execute("SELECT COUNT(*) FROM nav_point")
    print(f"  nav_point: {c.fetchone()[0]}")
    c = conn.execute("SELECT COUNT(*) FROM airway")
    print(f"  airway: {c.fetchone()[0]}")
    c = conn.execute("SELECT COUNT(*) FROM airway_segment")
    print(f"  airway_segment: {c.fetchone()[0]}")

    conn.close()

    if dataset.issues:
        print(f"\nIssues ({len(dataset.issues)}):")
        for iss in dataset.issues:
            print(f"  [{iss['severity']}] {iss['code']}: {iss['message']}")

    print(f"\n✓ Done")


if __name__ == "__main__":
    main()
