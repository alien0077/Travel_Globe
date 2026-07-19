#!/usr/bin/env python3
"""
泰國 eAIP Parser - 將泰國 CAAT eAIP HTML 解析為 SQLite

解析 Thailand ENR 文件：
  - ENR 4.4 → NavPoints (waypoints)
  - ENR 3.1 → Lower/Upper ATS routes + segments
  - ENR 3.3 → RNAV routes + segments
  - ENR 3.5 → Other routes + segments

用法：
  # 指定 raw 目錄
  python scripts/parse_thailand.py --dir data/raw/thailand/2026-07-09

  # 指定輸出 database
  python scripts/parse_thailand.py --dir data/raw/thailand/2026-07-09 --db data/processed/aviation-th.sqlite
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 共用工具（直接內建，不依賴 aviationdb 套件，保持獨立性）
# ---------------------------------------------------------------------------

EARTH_RADIUS_NM = 3440.065


class CoordinateParseError(ValueError):
    pass


def parse_coordinate(text: str) -> float:
    """解析單一座標字串 (e.g. '135337N') → decimal degrees"""
    value = text.strip().upper().replace(" ", "")
    match = re.fullmatch(r"([NSEW])?(\d+(?:\.\d+)?)([NSEW])?", value)
    if not match:
        raise CoordinateParseError(f"Unable to parse coordinate: {text}")
    hemisphere = match.group(1) or match.group(3)
    if hemisphere is None:
        raise CoordinateParseError(f"Missing hemisphere: {text}")
    digits = match.group(2)
    is_lon = hemisphere in {"E", "W"}
    degree_digits = 3 if is_lon else 2
    if len(digits.split(".")[0]) < degree_digits + 4:
        raise CoordinateParseError(f"Coordinate too short: {text}")
    degrees = int(digits[:degree_digits])
    minutes = int(digits[degree_digits : degree_digits + 2])
    seconds = float(digits[degree_digits + 2 :])
    decimal = degrees + minutes / 60 + seconds / 3600
    if hemisphere in {"S", "W"}:
        decimal *= -1
    return decimal


def parse_coordinate_pair(text: str) -> tuple[float, float]:
    """解析座標對 '135337N 1003546E' → (lat, lon)"""
    tokens = re.findall(r"\d+(?:\.\d+)?\s*[NSEW]", text.upper())
    if len(tokens) >= 2:
        return parse_coordinate(tokens[0]), parse_coordinate(tokens[1])
    raise CoordinateParseError(f"Cannot parse pair: {text}")


_COORD_RE = re.compile(r"\d{6}(?:\.\d+)?[NS]\s*\d{7}(?:\.\d+)?[EW]", re.IGNORECASE)


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_NM * asin(sqrt(a))


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import atan2, cos, radians, sin

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
    name: str | None = None
    country: str | None = "TH"
    fir: str | None = "BANGKOK"
    region_code: str | None = "asia-southeast"
    usage_type: str | None = "ENROUTE"


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
# UID 產生
# ---------------------------------------------------------------------------


def _stable_uid(prefix: str, *parts: object) -> str:
    from hashlib import sha256

    payload = "|".join("" if part is None else str(part) for part in parts)
    return f"{prefix}-{sha256(payload.encode()).hexdigest()[:16]}"


def _point_uid(ident: str, lat: float, lon: float, fir: str, point_type: str) -> str:
    return _stable_uid("pt", normalize_ident(ident), f"{lat:.6f}", f"{lon:.6f}", fir, point_type)


def _airway_uid(designator: str, source_id: str) -> str:
    return _stable_uid("awy", normalize_ident(designator), source_id, "BANGKOK")


def _segment_uid(airway_id: str, seq: int, from_uid: str, to_uid: str) -> str:
    return _stable_uid("seg", airway_id, seq, from_uid, to_uid)


# ---------------------------------------------------------------------------
# HTML Table 解析
# ---------------------------------------------------------------------------


def _extract_tables(html: str) -> list[list[list[str]]]:
    """從 HTML 中提取所有表格。"""
    from html.parser import HTMLParser

    class _Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.tables: list[list[list[str]]] = []
            self._table: list[list[str]] | None = None
            self._row: list[str] | None = None
            self._cell: list[str] | None = None

        def handle_starttag(self, tag: str, _attrs: Any) -> None:
            if tag == "table":
                self._table = []
            elif tag == "tr" and self._table is not None:
                self._row = []
            elif tag in {"td", "th"} and self._row is not None:
                self._cell = []

        def handle_data(self, data: str) -> None:
            if self._cell is not None:
                self._cell.append(data)

        def handle_endtag(self, tag: str) -> None:
            if tag in {"td", "th"} and self._row is not None and self._cell is not None:
                self._row.append(" ".join("".join(self._cell).split()))
                self._cell = None
            elif tag == "tr" and self._table is not None and self._row is not None:
                if self._row:
                    self._table.append(self._row)
                self._row = None
            elif tag == "table" and self._table is not None:
                self.tables.append(self._table)
                self._table = None

    parser = _Parser()
    parser.feed(html)
    return parser.tables


# ---------------------------------------------------------------------------
# ENR 4.4 - Significant Points
# ---------------------------------------------------------------------------

_FIR = "BANGKOK"
_COUNTRY = "TH"
_REGION = "asia-southeast"
_DESIGNATOR_RE = re.compile(r"^[A-Z]\d{1,4}[A-Z]?(?:\s*\([A-Z0-9 ]+\))?$")


def _parse_enr44_points(html: str, source_id: str, issues: list[dict[str, str]]) -> list[NavPoint]:
    points: list[NavPoint] = []
    for table in _extract_tables(html):
        if not table:
            continue
        header = " ".join(table[0]).upper().replace(" ", "")
        if "NAME-CODE" not in header and "NAMECODE" not in header:
            continue
        for row in table[1:]:
            if len(row) < 2 or row[0].strip().isdigit():
                continue
            ident = row[0].strip().upper()
            coords = row[1].strip()
            if not ident or not coords:
                continue
            try:
                lat, lon = parse_coordinate_pair(coords)
            except CoordinateParseError as e:
                issues.append({"severity": "warning", "code": "th-enr44-coord", "message": f"{ident}: {e}"})
                continue
            points.append(
                NavPoint(
                    uid=_point_uid(ident, lat, lon, _FIR, "SIGNIFICANT_POINT"),
                    ident=ident,
                    latitude=lat,
                    longitude=lon,
                    point_type="SIGNIFICANT_POINT",
                    source_id=source_id,
                    name=ident,
                    country=_COUNTRY,
                    fir=_FIR,
                    region_code=_REGION,
                    usage_type="ENROUTE",
                )
            )
    return points


# ---------------------------------------------------------------------------
# ENR 3.x - ATS Routes
# ---------------------------------------------------------------------------


def _clean_ident(value: str) -> str:
    head = re.split(r"[\s(]", value.strip(), maxsplit=1)[0]
    return normalize_ident(re.sub(r"[^A-Z0-9]", "", head.upper()))


def _clean_route_ident(value: str) -> str:
    upper = value.upper()
    if any(tok in upper for tok in ["VOR", "DME", "NDB"]):
        m = re.search(r"\(([A-Z0-9]{2,5})\)", upper)
        if m:
            return normalize_ident(m.group(1))
    return _clean_ident(value)


def _nav_point_from_row(row: list[str], source_id: str, issues: list[dict[str, str]]) -> NavPoint | None:
    """從 route table 的一列中解析 waypoint。"""
    for i in range(min(len(row), 4)):
        if _COORD_RE.search(row[i]):
            coord_idx = i
            break
    else:
        return None

    raw_ident = row[coord_idx - 1].strip() if coord_idx > 0 else ""
    if not raw_ident or raw_ident in {"▲", "∆", "▼"}:
        return None

    ident = _clean_route_ident(raw_ident)
    if not ident:
        return None

    try:
        lat, lon = parse_coordinate_pair(row[coord_idx])
    except CoordinateParseError as e:
        issues.append({"severity": "warning", "code": "th-route-coord", "message": f"{raw_ident}: {e}"})
        return None

    is_navaid = "(" in raw_ident and any(tok in raw_ident.upper() for tok in ["VOR", "DME", "NDB"])
    point_type = "NAVAID" if is_navaid else "SIGNIFICANT_POINT"

    return NavPoint(
        uid=_point_uid(ident, lat, lon, _FIR, point_type),
        ident=ident,
        latitude=lat,
        longitude=lon,
        point_type=point_type,
        source_id=source_id,
        name=ident,
        country=_COUNTRY,
        fir=_FIR,
        region_code=_REGION,
        usage_type="ENROUTE",
    )


def _distance_from_row(row: list[str]) -> float | None:
    """從列中提取距離值。"""
    for cell in row:
        # Match "NN.N NM" or "NN.N"
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:NM)?$", cell.strip().upper())
        if m:
            val = float(m.group(1))
            if 0.1 <= val <= 9999:
                return val
    return None


def _route_designator(table: list[list[str]]) -> tuple[str | None, str | None]:
    """從表格中提取 airway designator。"""
    for row in table[:10]:
        if not row:
            continue
        candidate = row[0].strip()
        if candidate.upper().startswith(("ROUTE DESIGNATOR", "1", "▼", "↑")):
            continue
        if _DESIGNATOR_RE.match(candidate.upper()) is None:
            continue
        route_type_m = re.search(r"\(([^)]+)\)", candidate)
        designator = normalize_ident(re.sub(r"\s*\([^)]+\)", "", candidate))
        route_type = normalize_ident(route_type_m.group(1)) if route_type_m else "ATS"
        return designator, route_type
    return None, None


def _parse_route_table(
    table: list[list[str]],
    table_idx: int,
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[dict[str, str]],
) -> tuple[Airway, list[AirwaySegment]] | None:
    designator, route_type = _route_designator(table)
    if designator is None:
        return None

    airway = Airway(
        uid=_airway_uid(designator, source_id),
        designator=designator,
        route_type=route_type,
        country=_COUNTRY,
        fir=_FIR,
        source_id=source_id,
    )

    route_points: list[NavPoint] = []
    route_segments: list[AirwaySegment] = []
    pending_distance: float | None = None

    for row in table:
        point = _nav_point_from_row(row, source_id, issues)
        if point is None:
            d = _distance_from_row(row)
            if d is not None:
                pending_distance = d
            continue

        stored = point_by_ident.get(point.ident)
        if stored is None:
            point_by_ident[point.ident] = point
            dataset_points.append(point)
            stored = point

        if route_points:
            prev = route_points[-1]
            seq = len(route_points)
            dist = pending_distance or haversine_nm(
                prev.latitude, prev.longitude, stored.latitude, stored.longitude
            )
            course = initial_bearing(prev.latitude, prev.longitude, stored.latitude, stored.longitude)
            route_segments.append(
                AirwaySegment(
                    uid=_segment_uid(airway.uid, seq, prev.uid, stored.uid),
                    airway_uid=airway.uid,
                    sequence=seq,
                    from_point_uid=prev.uid,
                    to_point_uid=stored.uid,
                    distance_nm=round(dist, 2),
                    initial_course_deg=round(course, 1),
                    reverse_course_deg=round((course + 180) % 360, 1),
                    source_id=source_id,
                )
            )

        route_points.append(stored)
        pending_distance = None

    if len(route_points) < 2:
        issues.append({"severity": "warning", "code": "th-route-too-short", "message": f"table {table_idx}: {designator}"})
        return None

    return airway, route_segments


# ---------------------------------------------------------------------------
# SQLite 匯出
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_metadata (
    source_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    country TEXT,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    airac_cycle TEXT,
    effective_date TEXT,
    retrieved_at TEXT NOT NULL,
    raw_file_sha256 TEXT NOT NULL,
    license_url TEXT,
    redistribution_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nav_point (
    uid TEXT PRIMARY KEY,
    ident TEXT NOT NULL,
    name TEXT,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    point_type TEXT NOT NULL,
    usage_type TEXT,
    country TEXT,
    fir TEXT,
    region_code TEXT,
    source_id TEXT NOT NULL,
    airac_cycle TEXT,
    effective_date TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS airway (
    uid TEXT PRIMARY KEY,
    designator TEXT NOT NULL,
    route_type TEXT,
    direction TEXT,
    country TEXT,
    fir TEXT,
    source_id TEXT NOT NULL,
    airac_cycle TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS airway_segment (
    uid TEXT PRIMARY KEY,
    airway_uid TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    from_point_uid TEXT NOT NULL,
    to_point_uid TEXT NOT NULL,
    distance_nm REAL,
    initial_course_deg REAL,
    reverse_course_deg REAL,
    direction TEXT,
    source_id TEXT NOT NULL,
    airac_cycle TEXT
);

CREATE INDEX IF NOT EXISTS idx_np_ident ON nav_point(ident);
CREATE INDEX IF NOT EXISTS idx_awy_desig ON airway(designator);
CREATE INDEX IF NOT EXISTS idx_seg_awy ON airway_segment(airway_uid, sequence);
CREATE INDEX IF NOT EXISTS idx_seg_from ON airway_segment(from_point_uid);
CREATE INDEX IF NOT EXISTS idx_seg_to ON airway_segment(to_point_uid);
"""


def _create_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _insert_dataset(conn: sqlite3.Connection, dataset: ParsedDataset, source_id: str, cycle: str) -> None:
    # 插入 source metadata
    conn.execute(
        """INSERT OR REPLACE INTO source_metadata
           (source_id, provider, country, source_url, source_type, airac_cycle,
            effective_date, retrieved_at, raw_file_sha256, license_url, redistribution_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            source_id,
            "Civil Aviation Authority of Thailand (CAAT)",
            "TH",
            "https://ais.caat.or.th/",
            "eaip_xhtml",
            cycle,
            cycle,
            datetime.now(UTC).isoformat(),
            "manual",
            None,
            "manual_review_required",
        ),
    )

    # 插入 points
    for pt in dataset.points:
        conn.execute(
            """INSERT OR REPLACE INTO nav_point
               (uid, ident, name, latitude, longitude, point_type, usage_type,
                country, fir, region_code, source_id, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (pt.uid, pt.ident, pt.name, pt.latitude, pt.longitude, pt.point_type,
             pt.usage_type, pt.country, pt.fir, pt.region_code, pt.source_id),
        )

    # 插入 airways
    for awy in dataset.airways:
        conn.execute(
            """INSERT OR REPLACE INTO airway
               (uid, designator, route_type, country, fir, source_id, is_active)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (awy.uid, awy.designator, awy.route_type, awy.country, awy.fir, awy.source_id),
        )

    # 插入 segments
    for seg in dataset.segments:
        conn.execute(
            """INSERT OR REPLACE INTO airway_segment
               (uid, airway_uid, sequence, from_point_uid, to_point_uid,
                distance_nm, initial_course_deg, reverse_course_deg, source_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (seg.uid, seg.airway_uid, seg.sequence, seg.from_point_uid,
             seg.to_point_uid, seg.distance_nm, seg.initial_course_deg,
             seg.reverse_course_deg, seg.source_id),
        )

    conn.commit()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_documents(documents: dict[str, str], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}

    for doc_id, html in documents.items():
        if doc_id == "enr_4_4":
            for pt in _parse_enr44_points(html, source_id, dataset.issues):
                point_by_ident.setdefault(pt.ident, pt)
                dataset.points.append(pt)
            print(f"  ENR 4.4: {len([p for p in dataset.points if p.source_id == source_id])} points")
            continue

        if doc_id in ("enr_3_1", "enr_3_3", "enr_3_5"):
            tables = _extract_tables(html)
            route_count = 0
            seg_count = 0
            for ti, table in enumerate(tables, start=1):
                result = _parse_route_table(table, ti, source_id, point_by_ident, dataset.points, dataset.issues)
                if result is None:
                    continue
                awy, segs = result
                dataset.airways.append(awy)
                dataset.segments.extend(segs)
                route_count += 1
                seg_count += len(segs)
            print(f"  {doc_id}: {route_count} routes, {seg_count} segments")

    return dataset


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Parse Thailand eAIP HTML files into SQLite")
    parser.add_argument("--dir", required=True, help="Raw data directory (e.g. data/raw/thailand/2026-07-09)")
    parser.add_argument("--db", default=None, help="Output SQLite path (default: data/processed/aviation-th.sqlite)")
    parser.add_argument("--source-id", default="thailand", help="Source identifier")
    args = parser.parse_args()

    raw_dir = Path(args.dir)
    if not raw_dir.is_dir():
        print(f"✗ 目錄不存在: {raw_dir}")
        sys.exit(1)

    project_root = Path(__file__).resolve().parent.parent
    db_path = Path(args.db) if args.db else project_root / "data" / "processed" / "aviation-th.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # 載入 doc_id → file path 對應
    documents: dict[str, str] = {}

    # 嘗試從 manifest.json 讀取
    manifest_path = raw_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for art in manifest.get("artifacts", []):
            rel_path = art.get("target") or art.get("path", "")
            if not rel_path:
                continue
            art_path = project_root / rel_path
            if art_path.exists():
                documents[art["id"]] = art_path.read_text(encoding="utf-8", errors="replace")

    # fallback: 直接掃描目錄
    if not documents:
        file_map = {
            "enr_4_4": "VT-ENR-4.4-en-GB.html",
            "enr_3_1": "VT-ENR-3.1-en-GB.html",
            "enr_3_3": "VT-ENR-3.3-en-GB.html",
            "enr_3_5": "VT-ENR-3.5-en-GB.html",
        }
        for doc_id, fname in file_map.items():
            fp = raw_dir / fname
            if fp.exists():
                documents[doc_id] = fp.read_text(encoding="utf-8", errors="replace")

    if not documents:
        print(f"✗ 找不到任何 HTML 檔案在 {raw_dir}")
        print(f"  請先執行 python scripts/download_thailand.py 或手動下載")
        sys.exit(1)

    # 確認至少有必要文件
    required_ids = {"enr_4_4", "enr_3_1"}
    missing = required_ids - set(documents.keys())
    if missing:
        print(f"✗ 缺少必要文件: {missing}")
        sys.exit(1)

    cycle = raw_dir.name
    source_id = args.source_id

    print(f"解析泰國 eAIP...")
    print(f"  來源: {raw_dir}")
    print(f"  輸出: {db_path}")
    print()

    dataset = parse_documents(documents, source_id)

    print()
    print(f"結果:")
    print(f"  NavPoints: {len(dataset.points)}")
    print(f"  Airways:   {len(dataset.airways)}")
    print(f"  Segments:  {len(dataset.segments)}")
    print(f"  Issues:    {len(dataset.issues)}")

    print()
    print(f"寫入 SQLite: {db_path}")
    conn = _create_db(db_path)
    _insert_dataset(conn, dataset, source_id, cycle)

    # 輸出統計
    print()
    cursor = conn.execute("SELECT COUNT(*) FROM nav_point")
    print(f"  nav_point: {cursor.fetchone()[0]}")
    cursor = conn.execute("SELECT COUNT(*) FROM airway")
    print(f"  airway: {cursor.fetchone()[0]}")
    cursor = conn.execute("SELECT COUNT(*) FROM airway_segment")
    print(f"  airway_segment: {cursor.fetchone()[0]}")

    conn.close()

    if dataset.issues:
        print()
        print("Warnings:")
        for iss in dataset.issues[:10]:
            print(f"  [{iss['severity']}] {iss['code']}: {iss['message']}")
        if len(dataset.issues) > 10:
            print(f"  ... and {len(dataset.issues) - 10} more")

    print()
    print("✓ 完成")
    print(f"  下一步: 可執行 python -c \"import sqlite3; c=sqlite3.connect('{db_path}'); print(c.execute('SELECT designator,COUNT(*) FROM airway GROUP BY designator').fetchall())\"")


if __name__ == "__main__":
    main()
