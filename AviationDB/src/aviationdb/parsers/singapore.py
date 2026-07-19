from __future__ import annotations

import re

from aviationdb.geo import CoordinateParseError, haversine_nm, initial_bearing_degrees, parse_coordinate_pair
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.html_table import extract_tables
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "SINGAPORE"
COUNTRY = "SG"
REGION = "asia-southeast"
COORDINATE_PAIR_RE = re.compile(r"\d{6}(?:\.\d+)?[NS]\s*\d{7}(?:\.\d+)?[EW]", re.IGNORECASE)
DESIGNATOR_RE = re.compile(r"^[A-Z]\d{1,4}[A-Z]?(?:\s*\([A-Z0-9 ]+\))?$")


def parse_singapore_eaip_documents(documents: dict[str, str], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}

    for document_id, html in documents.items():
        if document_id == "enr_4_4":
            for point in _parse_enr44_points(html, source_id, dataset.issues):
                point_by_ident.setdefault(point.ident, point)
                dataset.points.append(point)
            continue
        if document_id in {"enr_3_1", "enr_3_2"}:
            airways, segments = _parse_route_tables(html, source_id, point_by_ident, dataset.points, dataset.issues)
            dataset.airways.extend(airways)
            dataset.segments.extend(segments)

    return dataset


def _parse_enr44_points(html: str, source_id: str, issues: list[Issue]) -> list[NavPoint]:
    points: list[NavPoint] = []
    for table in extract_tables(html):
        if not table:
            continue
        header = " ".join(table[0]).upper().replace(" ", "")
        if "NAME-CODEDESIGNATOR" not in header or "COORDINATES" not in header:
            continue
        for row_number, row in enumerate(table[1:], start=2):
            if len(row) < 2 or row[0].strip().isdigit():
                continue
            ident = _clean_ident(row[0])
            coordinates = row[1].strip()
            if not ident or not coordinates:
                continue
            try:
                lat, lon = parse_coordinate_pair(coordinates)
            except CoordinateParseError as error:
                issues.append(
                    Issue("warning", "singapore-enr44-coordinate", f"row {row_number}: {error}", source_id, ident)
                )
                continue
            points.append(_nav_point(ident, lat, lon, "SIGNIFICANT_POINT", source_id))
    return points


def _parse_route_tables(
    html: str,
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[Issue],
) -> tuple[list[Airway], list[AirwaySegment]]:
    airways: list[Airway] = []
    segments: list[AirwaySegment] = []
    for table_index, table in enumerate(extract_tables(html), start=1):
        parsed = _parse_route_table(table, table_index, source_id, point_by_ident, dataset_points, issues)
        if parsed is None:
            continue
        airway, route_segments = parsed
        airways.append(airway)
        segments.extend(route_segments)
    return airways, segments


def _parse_route_table(
    table: list[list[str]],
    table_index: int,
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[Issue],
) -> tuple[Airway, list[AirwaySegment]] | None:
    designator, route_type = _route_designator(table)
    if designator is None:
        return None
    airway = Airway(
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
        point = _point_from_row(row, source_id, issues)
        if point is None:
            pending_distance = _distance_from_row(row) or pending_distance
            continue
        stored_point = point_by_ident.get(point.ident)
        if stored_point is None:
            stored_point = point
            point_by_ident[point.ident] = stored_point
            dataset_points.append(stored_point)
        if route_points:
            previous = route_points[-1]
            sequence = len(route_points)
            distance = pending_distance or haversine_nm(
                (previous.latitude, previous.longitude),
                (stored_point.latitude, stored_point.longitude),
            )
            course = initial_bearing_degrees(
                (previous.latitude, previous.longitude),
                (stored_point.latitude, stored_point.longitude),
            )
            route_segments.append(
                AirwaySegment(
                    uid=segment_uid(airway.uid, sequence, previous.uid, stored_point.uid),
                    airway_uid=airway.uid,
                    sequence=sequence,
                    from_point_uid=previous.uid,
                    to_point_uid=stored_point.uid,
                    distance_nm=round(distance, 2),
                    initial_course_deg=round(course, 1),
                    reverse_course_deg=round((course + 180) % 360, 1),
                    source_id=source_id,
                )
            )
        route_points.append(stored_point)
        pending_distance = None

    if len(route_points) < 2:
        issues.append(Issue("warning", "singapore-route-too-short", f"table {table_index}: {designator}", source_id))
        return None
    return airway, route_segments


def _route_designator(table: list[list[str]]) -> tuple[str | None, str | None]:
    for row in table[:8]:
        if not row:
            continue
        candidate = row[0].strip()
        if candidate.upper().startswith(("ROUTE DESIGNATOR", "1")):
            continue
        if DESIGNATOR_RE.match(candidate.upper()) is None:
            continue
        route_type_match = re.search(r"\(([^)]+)\)", candidate)
        designator = normalize_ident(re.sub(r"\s*\([^)]+\)", "", candidate))
        route_type = normalize_ident(route_type_match.group(1)) if route_type_match else "ATS"
        return designator, route_type
    return None, None


def _point_from_row(row: list[str], source_id: str, issues: list[Issue]) -> NavPoint | None:
    if len(row) < 3 or COORDINATE_PAIR_RE.search(row[2]) is None:
        return None
    raw_ident = row[1].strip()
    ident = _clean_route_ident(raw_ident)
    if not ident:
        return None
    try:
        lat, lon = parse_coordinate_pair(row[2])
    except CoordinateParseError as error:
        issues.append(Issue("warning", "singapore-route-coordinate", str(error), source_id, ident))
        return None
    is_navaid = "(" in raw_ident and any(token in raw_ident.upper() for token in ["VOR", "DME", "NDB"])
    point_type = "NAVAID" if is_navaid else "SIGNIFICANT_POINT"
    return _nav_point(ident, lat, lon, point_type, source_id)


def _distance_from_row(row: list[str]) -> float | None:
    for cell in row:
        match = re.search(r"(\d+(?:\.\d+)?)\s*NM\b", cell.upper())
        if match:
            return float(match.group(1))
    return None


def _clean_ident(value: str) -> str:
    head = re.split(r"[\s(]", value.strip(), maxsplit=1)[0]
    return normalize_ident(re.sub(r"[^A-Z0-9]", "", head.upper()))


def _clean_route_ident(value: str) -> str:
    upper = value.upper()
    if any(token in upper for token in ["VOR", "DME", "NDB"]):
        match = re.search(r"\(([A-Z0-9]{2,5})\)", upper)
        if match:
            return normalize_ident(match.group(1))
    return _clean_ident(value)


def _nav_point(ident: str, lat: float, lon: float, point_type: str, source_id: str) -> NavPoint:
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
