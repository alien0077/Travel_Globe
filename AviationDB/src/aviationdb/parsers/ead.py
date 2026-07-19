"""EAD Basic SDO Report Parser - canonical build integration.

Parses EAD Basic SDO Reporting HTML output containing structured
aeronautical data (Upper Routes, Non-upper Routes, Designated Points).

Report format:
  Master gUID | Route Designator | Area Desig. | Start identifier | Type |
  End Identifier | Type | Upper limit | ... | Lower limit | ... | Originator
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from aviationdb.geo import haversine_nm, initial_bearing_degrees
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "EAD_EUROPE"
COUNTRY = "EU"
REGION = "europe"

# All points use a uniform FIR for UID consistency
EAD_FIR = "EAD_EUROPE"

# FIR mapping by area designator prefix
FIR_BY_AREA: dict[str, str] = {
    "EB": "BRUSSELS", "ED": "GERMANY", "EH": "AMSTERDAM",
    "LF": "PARIS", "LG": "ATHINAI", "LI": "ROMA",
    "LO": "WIEN", "LS": "SWITZERLAND", "LT": "ANKARA",
    "EV": "RIGA", "EY": "VILNIUS", "EK": "COPENHAGEN",
    "EN": "NORWAY", "ES": "SWEDEN", "EF": "FINLAND",
    "ET": "GERMANY", "DA": "ALGIERS", "DN": "NIGER",
    "FC": "BRAZZAVILLE", "FI": "MAURITIUS", "FL": "HARARE",
    "FV": "HARARE", "FZ": "KINSHASA", "GM": "CASABLANCA",
    "GO": "DAKAR", "HA": "ADDIS_ABABA", "HC": "MOGADISHU",
    "HK": "NAIROBI", "VO": "MUMBAI", "HE": "CAIRO",
    "HL": "TRIPOLI", "HR": "KHARTOUM",
}
DEFAULT_FIR = "EAD_EUROPE"
COUNTRY_BY_AREA: dict[str, str] = {
    "EB": "BE", "ED": "DE", "EH": "NL", "LF": "FR",
    "LG": "GR", "LI": "IT", "LO": "AT", "LS": "CH",
    "LT": "TR", "EV": "LV", "EY": "LT", "EK": "DK",
    "EN": "NO", "ES": "SE", "EF": "FI", "DA": "DZ",
}
DEFAULT_COUNTRY = "EU"

# Point type mapping from EAD types
POINT_TYPE_MAP = {
    "WPT": "SIGNIFICANT_POINT",
    "VOR/DME": "NAVAID",
    "VOR": "NAVAID",
    "DME": "NAVAID",
    "NDB": "NAVAID",
    "VORTAC": "NAVAID",
    "TACAN": "NAVAID",
}

AREA_DESIG_RE = re.compile(r"([A-Z]{2})")


def _country_from_area(area: str) -> str:
    m = AREA_DESIG_RE.match(area)
    if m:
        return COUNTRY_BY_AREA.get(m.group(1), DEFAULT_COUNTRY)
    if area == "EUR":
        return DEFAULT_COUNTRY
    return DEFAULT_COUNTRY


def _fir_from_area(area: str) -> str:
    m = AREA_DESIG_RE.match(area)
    if m:
        return FIR_BY_AREA.get(m.group(1), DEFAULT_FIR)
    return DEFAULT_FIR


class EADHTMLTableParser(HTMLParser):
    """Parse the SDO report HTML table into rows of cells."""
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._in_data_table = False
        self._table_count = 0
        self._row_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table_count += 1
            # The data table is the second <table> in the document
            if self._table_count == 2:
                self._in_data_table = True
        if self._in_data_table:
            if tag == "tr":
                self._current_row = []
                self._row_count += 1
            if tag in {"td", "th"} and self._current_row is not None:
                self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._in_data_table:
            if tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
                text = " ".join("".join(self._current_cell).split())
                self._current_row.append(text)
                self._current_cell = None
            if tag == "tr" and self._current_row is not None:
                if any(c.strip() for c in self._current_row):
                    self.rows.append(self._current_row)
                self._current_row = None
            if tag == "table":
                self._in_data_table = False


def parse_ead_html_report(html: str, source_id: str) -> ParsedDataset:
    """Parse an EAD SDO report HTML into ParsedDataset.
    
    The report format contains rows of route segments:
    RouteDesignator | Area | StartIdent | StartType | EndIdent | EndType | ...
    """
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}

    parser = EADHTMLTableParser()
    parser.feed(html)

    # Group rows by route designator
    route_rows: dict[str, list[list[str]]] = {}
    for row in parser.rows:
        if len(row) < 7:
            continue
        designator = normalize_ident(row[1]) if len(row) > 1 else ""
        if not designator or not re.match(r"^[A-Z]{1,2}\d", designator):
            continue
        if designator not in route_rows:
            route_rows[designator] = []
        route_rows[designator].append(row)

    # Process each route
    for designator, rows in route_rows.items():
        area = rows[0][2] if len(rows[0]) > 2 else "EUR"
        fir = _fir_from_area(area)
        country = _country_from_area(area)

        awy = Airway(
            uid=airway_uid(designator, source_id, fir),
            designator=designator,
            route_type="RNAV" if designator.startswith(("U", "P", "Q", "T", "Z")) else "ATS",
            country=country,
            fir=fir,
            source_id=source_id,
        )

        route_points: list[NavPoint] = []
        route_segments: list[AirwaySegment] = []
        pending_dist: float | None = None

        for row in rows:
            if len(row) < 7:
                continue
            start_ident = normalize_ident(row[3]) if len(row) > 3 else ""
            start_type = row[4] if len(row) > 4 else "WPT"
            end_ident = normalize_ident(row[5]) if len(row) > 5 else ""
            end_type = row[6] if len(row) > 6 else "WPT"

            if not start_ident or not end_ident:
                continue

            # Create or reuse start point (uniform EAD_FIR for UID consistency)
            if start_ident not in point_by_ident:
                pt_type = POINT_TYPE_MAP.get(start_type, "SIGNIFICANT_POINT")
                pt = NavPoint(
                    uid=point_uid(start_ident, 0.0, 0.0, EAD_FIR, pt_type, source_id),
                    ident=start_ident,
                    name=start_ident,
                    latitude=0.0,
                    longitude=0.0,
                    point_type=pt_type,
                    usage_type="ENROUTE",
                    country=country,
                    fir=fir,
                    region_code=REGION,
                    source_id=source_id,
                )
                point_by_ident[start_ident] = pt
                dataset.points.append(pt)

            # Create or reuse end point
            if end_ident not in point_by_ident:
                pt_type = POINT_TYPE_MAP.get(end_type, "SIGNIFICANT_POINT")
                pt = NavPoint(
                    uid=point_uid(end_ident, 0.0, 0.0, EAD_FIR, pt_type, source_id),
                    ident=end_ident,
                    name=end_ident,
                    latitude=0.0,
                    longitude=0.0,
                    point_type=pt_type,
                    usage_type="ENROUTE",
                    country=country,
                    fir=fir,
                    region_code=REGION,
                    source_id=source_id,
                )
                point_by_ident[end_ident] = pt
                dataset.points.append(pt)

            # Skip zero-length segments (same start and end)
            if start_ident == end_ident:
                continue

            # Don't add duplicate consecutive segments
            if route_points and route_points[-1].ident == end_ident:
                continue

            # Build segment
            start_pt = point_by_ident[start_ident]
            end_pt = point_by_ident[end_ident]

            seq = len(route_segments) + 1
            route_segments.append(
                AirwaySegment(
                    uid=segment_uid(awy.uid, seq, start_pt.uid, end_pt.uid),
                    airway_uid=awy.uid,
                    sequence=seq,
                    from_point_uid=start_pt.uid,
                    to_point_uid=end_pt.uid,
                    distance_nm=None,
                    initial_course_deg=None,
                    reverse_course_deg=None,
                    source_id=source_id,
                )
            )

            if start_ident not in [p.ident for p in route_points]:
                route_points.append(start_pt)
            route_points.append(end_pt)

        if route_segments:
            if not any(a.uid == awy.uid for a in dataset.airways):
                dataset.airways.append(awy)
            existing_seg_uids = {s.uid for s in dataset.segments}
            for seg in route_segments:
                if seg.uid not in existing_seg_uids:
                    existing_seg_uids.add(seg.uid)
                    dataset.segments.append(seg)

    point_uids = {p.uid for p in dataset.points}
    dataset.segments = [
        s for s in dataset.segments
        if s.from_point_uid in point_uids and s.to_point_uid in point_uids
    ]

    return dataset


def parse_ead_documents(source_id: str) -> ParsedDataset:
    """Parse all EAD report HTML files from data/raw/ead/."""
    from aviationdb.config import PROJECT_ROOT

    dataset = ParsedDataset()
    raw_dir = PROJECT_ROOT / "data" / "raw" / "ead"

    report_files = [
        ("upper-routes", "upper-routes-NE.html"),
        ("upper-routes", "upper-routes-NW.html"),
        ("upper-routes", "upper-routes-SW.html"),
    ]

    for subdir, filename in report_files:
        filepath = raw_dir / subdir / filename
        if not filepath.exists():
            continue

        html = filepath.read_text(encoding="utf-8", errors="replace")
        partial = parse_ead_html_report(html, source_id)

        existing_idents = {p.ident for p in dataset.points}
        for pt in partial.points:
            if pt.ident not in existing_idents:
                dataset.points.append(pt)
                existing_idents.add(pt.ident)

        dataset.airways.extend(partial.airways)
        dataset.segments.extend(partial.segments)
        dataset.issues.extend(partial.issues)

    # Fill coordinates from existing AviationDB database
    main_db = PROJECT_ROOT / "data" / "processed" / "aviation.sqlite"
    if main_db.exists():
        _fill_coordinates(dataset, main_db, source_id)

    # Fill coordinates from OpenAIP European dataset
    openaip_file = PROJECT_ROOT / "data" / "raw" / "openaip" / "european_coordinates.json"
    if openaip_file.exists():
        _fill_openaip_coordinates(dataset, openaip_file, source_id)

    # Fill coordinates from AIXM national datasets (Germany, Spain, etc.)
    aixm_file = PROJECT_ROOT / "data" / "raw" / "aixm" / "combined_aixm_coordinates.json"
    if aixm_file.exists():
        _fill_openaip_coordinates(dataset, aixm_file, source_id)

    # Fill coordinates from FlightGear (GPL, global coverage)
    fg_file = PROJECT_ROOT / "data" / "processed" / "aviation-flightgear-coords.json"
    if not fg_file.exists():
        _export_flightgear_coords(fg_file, source_id)
    if fg_file.exists():
        _fill_openaip_coordinates(dataset, fg_file, source_id)

    return dataset


def _export_flightgear_coords(output_path: Path, source_id: str) -> None:
    """Export FlightGear point coordinates to a JSON file for the resolver."""
    import json
    import sqlite3
    main_db = Path(__file__).resolve().parent.parent.parent / "data" / "processed" / "aviation.sqlite"
    if not main_db.exists():
        return
    try:
        conn = sqlite3.connect(str(main_db))
        rows = conn.execute(
            "SELECT ident, latitude, longitude, point_type FROM nav_point "
            "WHERE source_id='flightgear' AND latitude != 0"
        ).fetchall()
        conn.close()
        points = {}
        for ident, lat, lon, pt_type in rows:
            if ident not in points:
                points[ident] = {"lat": lat, "lon": lon, "type": pt_type or "SIGNIFICANT_POINT"}
        with open(output_path, "w") as f:
            json.dump({"source": "flightgear", "cycle": "2013.10",
                       "points": points}, f, indent=2)
    except Exception:
        pass


def _fill_coordinates(dataset: ParsedDataset, db_path: Path, source_id: str) -> None:
    """Fill EAD point coordinates by matching idents against existing nav_points."""
    import sqlite3
    try:
        conn = sqlite3.connect(str(db_path))
        ead_idents = [p.ident for p in dataset.points if p.latitude == 0.0]
        if not ead_idents:
            conn.close()
            return

        placeholders = ",".join("?" for _ in ead_idents)
        rows = conn.execute(
            f"SELECT ident, latitude, longitude, point_type FROM nav_point "
            f"WHERE ident IN ({placeholders}) AND latitude != 0 AND source_id != ?",
            ead_idents + [source_id],
        ).fetchall()

        coord_map: dict[str, tuple[float, float, str]] = {}
        for ident, lat, lon, pt_type in rows:
            if ident not in coord_map:
                coord_map[ident] = (lat, lon, pt_type or "SIGNIFICANT_POINT")

        conn.close()

        updated = 0
        for pt in dataset.points:
            if pt.latitude == 0.0 and pt.ident in coord_map:
                lat, lon, pt_type = coord_map[pt.ident]
                pt.__dict__["latitude"] = lat
                pt.__dict__["longitude"] = lon
                pt.__dict__["point_type"] = pt_type
                # Regenerate UID with correct coordinates
                from aviationdb.uid import point_uid
                pt.__dict__["uid"] = point_uid(
                    pt.ident, lat, lon, EAD_FIR, pt_type, source_id
                )
                updated += 1

        # Rebuild point_by_ident for segment UID consistency
        if updated > 0:
            point_uids = {p.uid for p in dataset.points}
            dataset.segments = [
                s for s in dataset.segments
                if s.from_point_uid in point_uids and s.to_point_uid in point_uids
            ]

    except Exception:
        pass  # Coordinate filling is best-effort


def _fill_openaip_coordinates(dataset: ParsedDataset, json_path: Path, source_id: str) -> None:
    """Fill EAD point coordinates from OpenAIP European dataset."""
    import json
    try:
        with open(json_path) as f:
            data = json.load(f)
        raw_points = data.get("points", {})
        if not raw_points:
            return
        # Build normalized lookup
        from aviationdb.uid import normalize_ident
        points_data: dict[str, object] = {}
        for k, v in raw_points.items():
            points_data[normalize_ident(k)] = v

        updated = 0
        for pt in dataset.points:
            if pt.latitude != 0.0:
                continue
            ident = pt.ident
            oa = points_data.get(ident)
            if oa is None:
                continue
            lat = oa["lat"]
            lon = oa["lon"]
            pt_type = "NAVAID" if oa.get("type") in ("VOR", "DME", "NDB", "VOR_DME", "VORTAC", "TACAN") else "SIGNIFICANT_POINT"
            pt.__dict__["latitude"] = lat
            pt.__dict__["longitude"] = lon
            pt.__dict__["point_type"] = pt_type
            from aviationdb.uid import point_uid
            pt.__dict__["uid"] = point_uid(pt.ident, lat, lon, EAD_FIR, pt_type, source_id)
            updated += 1

        if updated > 0:
            point_uids = {p.uid for p in dataset.points}
            dataset.segments = [
                s for s in dataset.segments
                if s.from_point_uid in point_uids and s.to_point_uid in point_uids
            ]
    except Exception:
        pass
