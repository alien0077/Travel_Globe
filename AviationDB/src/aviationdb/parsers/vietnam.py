"""Viet Nam VNAIC eAIP HTML Parser - canonical build integration."""
from __future__ import annotations

import re
from html.parser import HTMLParser

from aviationdb.geo import CoordinateParseError, haversine_nm, initial_bearing_degrees, parse_coordinate
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "HO_CHI_MINH"
COUNTRY = "VN"
REGION = "asia-southeast"

_COORD_RE = re.compile(r"\d{6}(?:\.\d+)?[NS]\s*\d{7}(?:\.\d+)?[EW]", re.IGNORECASE)
_TEMPLATE_MARKER_RE = re.compile(r"T[A-Z_]+;[A-Z_]+;\d+")


def parse_vietnam_eaip_documents(documents: dict[str, str], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}

    for doc_id, html in documents.items():
        if doc_id == "enr_4_4":
            pts = _parse_enr44_points(html, source_id, dataset.issues)
            for pt in pts:
                point_by_ident.setdefault(pt.ident, pt)
                dataset.points.append(pt)
        elif doc_id in ("enr_3_1", "enr_3_2"):
            tables = _extract_tables(html)
            for table in tables:
                result = _parse_route_table(table, source_id, point_by_ident, dataset.points, dataset.issues)
                if result is None:
                    continue
                awy, segs = result
                dataset.airways.append(awy)
                dataset.segments.extend(segs)

    return dataset


def _clean_template_markers(text: str) -> str:
    text = _TEMPLATE_MARKER_RE.sub("", text)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())


def _extract_tables(html: str) -> list[list[list[str]]]:
    class _Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.tables: list[list[list[str]]] = []
            self._table: list[list[str]] | None = None
            self._row: list[str] | None = None
            self._cell: list[str] | None = None

        def handle_starttag(self, tag: str, _attrs: object) -> None:
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
                raw = "".join(self._cell)
                cleaned = _clean_template_markers(raw)
                self._row.append(cleaned)
                self._cell = None
            elif tag == "tr" and self._table is not None and self._row is not None:
                if any(c.strip() for c in self._row):
                    self._table.append(self._row)
                self._row = None
            elif tag == "table" and self._table is not None:
                self.tables.append(self._table)
                self._table = None

    parser = _Parser()
    parser.feed(html)
    return parser.tables


def _parse_enr44_points(html: str, source_id: str, issues: list[Issue]) -> list[NavPoint]:
    points: list[NavPoint] = []
    for table in _extract_tables(html):
        if not table:
            continue
        header = " ".join(table[0]).upper().replace(" ", "")
        if "NAME-CODE" not in header and "NAMECODE" not in header:
            continue
        for row in table[1:]:
            if len(row) < 2:
                continue
            row_text = " ".join(row)
            coord_match = _COORD_RE.search(row_text)
            if not coord_match:
                continue
            before_coord = row_text[: coord_match.start()].strip()
            tokens = before_coord.split()
            ident_candidate = tokens[-1] if tokens else ""
            if not ident_candidate or ident_candidate.isdigit() or ident_candidate in {"▲", "∆", "▼"}:
                continue
            ident = normalize_ident(re.sub(r"[^A-Z0-9]", "", ident_candidate.upper()))
            if not ident:
                continue
            try:
                lat_str, lon_str = coord_match.group(0).split()
                lat = parse_coordinate(lat_str)
                lon = parse_coordinate(lon_str)
            except (CoordinateParseError, ValueError):
                continue
            points.append(
                NavPoint(
                    uid=point_uid(ident, lat, lon, FIR, "SIGNIFICANT_POINT", source_id),
                    ident=ident,
                    name=ident,
                    latitude=lat,
                    longitude=lon,
                    point_type="SIGNIFICANT_POINT",
                    usage_type="ENROUTE",
                    country=COUNTRY,
                    fir=FIR,
                    region_code=REGION,
                    source_id=source_id,
                )
            )
    return points


def _clean_route_ident(value: str) -> str:
    upper = value.upper()
    if any(tok in upper for tok in ["VOR", "DME", "NDB"]):
        m = re.search(r"\(([A-Z0-9]{2,5})\)", upper)
        if m:
            return normalize_ident(m.group(1))
    head = re.split(r"[\s(]", value.strip(), maxsplit=1)[0]
    return normalize_ident(re.sub(r"[^A-Z0-9]", "", head.upper()))


def _parse_route_table(
    table: list[list[str]],
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[Issue],
) -> tuple[Airway, list[AirwaySegment]] | None:
    designator, route_type = _route_designator(table)
    if designator is None:
        return None
    if any("continuation" in " ".join(r).lower() for r in table[:3]):
        return None

    awy = Airway(
        uid=airway_uid(designator, source_id, FIR),
        designator=designator,
        route_type=route_type,
        country=COUNTRY,
        fir=FIR,
        source_id=source_id,
    )
    route_points: list[NavPoint] = []
    route_segments: list[AirwaySegment] = []
    pending_distance: float | None = None

    for row in table:
        row_text = " ".join(row)
        if row_text.upper().startswith(("ROUTE DESIGNATOR", "1", "SIGNIFICANT")):
            continue
        point = _nav_point_from_row(row, source_id, issues)
        if point is None:
            d = _distance_from_row_text(row_text)
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
                (prev.latitude, prev.longitude), (stored.latitude, stored.longitude)
            )
            course = initial_bearing_degrees((prev.latitude, prev.longitude), (stored.latitude, stored.longitude))
            route_segments.append(
                AirwaySegment(
                    uid=segment_uid(awy.uid, seq, prev.uid, stored.uid),
                    airway_uid=awy.uid,
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
        return None
    return awy, route_segments


def _route_designator(table: list[list[str]]) -> tuple[str | None, str | None]:
    for row in table[:10]:
        if not row:
            continue
        cell = row[0].strip()
        if cell.upper().startswith(("ROUTE DESIGNATOR", "1")):
            continue
        m = re.match(r"^([A-Z]\d{1,4}[A-Z]?)", cell.upper())
        if m:
            designator = normalize_ident(m.group(1))
            route_type = "ATS"
            if "RNAV" in cell.upper() or "RNP" in cell.upper():
                rt_m = re.search(r"\(([^)]+)\)", cell)
                if rt_m:
                    route_type = normalize_ident(rt_m.group(1))
            return designator, route_type
    return None, None


def _nav_point_from_row(row: list[str], source_id: str, issues: list[Issue]) -> NavPoint | None:
    row_text = " ".join(row)
    coord_match = _COORD_RE.search(row_text)
    if not coord_match:
        return None
    before_coord = row_text[: coord_match.start()].strip()
    before_coord = re.sub(r"^[▲∆▼]\s*", "", before_coord).strip()
    tokens = before_coord.split()
    if not tokens:
        return None
    raw_ident = tokens[0]
    raw_ident = re.sub(r"^\(?\d+\)?\s*", "", raw_ident).strip()
    if not raw_ident or raw_ident.isdigit():
        return None
    ident = _clean_route_ident(raw_ident)
    if not ident:
        return None
    try:
        lat_str, lon_str = coord_match.group(0).split()
        lat = parse_coordinate(lat_str)
        lon = parse_coordinate(lon_str)
    except (CoordinateParseError, ValueError):
        return None

    is_navaid = "(" in raw_ident and any(tok in raw_ident.upper() for tok in ["VOR", "DME", "NDB"])
    point_type = "NAVAID" if is_navaid else "SIGNIFICANT_POINT"
    return NavPoint(
        uid=point_uid(ident, lat, lon, FIR, point_type, source_id),
        ident=ident,
        name=ident,
        latitude=lat,
        longitude=lon,
        point_type=point_type,
        usage_type="ENROUTE",
        country=COUNTRY,
        fir=FIR,
        region_code=REGION,
        source_id=source_id,
    )


def _distance_from_row_text(row_text: str) -> float | None:
    km_match = re.search(r"(\d+(?:\.\d+)?)\s*KM", row_text.upper())
    if km_match:
        val = float(km_match.group(1))
        if 0.1 <= val <= 9999:
            return round(val * 0.539957, 2)
    num_match = re.search(r"(?<!\d)(\d{2,3}(?:\.\d+)?)(?!\s*[°T])", row_text)
    if num_match:
        val = float(num_match.group(1))
        if 5 <= val <= 9999:
            return val
    return None
