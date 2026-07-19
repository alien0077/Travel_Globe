from __future__ import annotations

import re

from aviationdb.geo import CoordinateParseError, haversine_nm, initial_bearing_degrees, parse_coordinate_pair
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.html_table import extract_tables
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "INDIA"
COUNTRY = "IN"
REGION = "asia-south"

COORDINATE_PAIR_RE = re.compile(
    r"(?P<lat>\d{6}(?:\.\d+)?[NS])\s*(?P<lon>\d{7}(?:\.\d+)?[EW])",
    re.IGNORECASE,
)
ROUTE_DESIGNATOR_RE = re.compile(r"\b([A-Z]{1,2}\d{1,4}[A-Z]?)\b")
NAVAID_WORDS = {"DME", "DVOR", "NDB", "VOR", "VOR/DME", "VORTAC"}


def parse_india_eaip_documents(documents: dict[str, str], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}

    for document_id, html in documents.items():
        if document_id == "enr_4_4":
            for point in _parse_enr44_points(html, source_id, dataset.issues):
                _store_point(point, point_by_ident, dataset.points)

    for document_id, html in documents.items():
        if not document_id.startswith("route_"):
            continue
        airways, segments = _parse_route_document(
            html,
            document_id,
            source_id,
            point_by_ident,
            dataset.points,
            dataset.issues,
        )
        dataset.airways.extend(airways)
        dataset.segments.extend(segments)

    return dataset


def _parse_enr44_points(html: str, source_id: str, issues: list[Issue]) -> list[NavPoint]:
    points: list[NavPoint] = []
    for table in extract_tables(html):
        if not table:
            continue
        header = " ".join(table[0]).upper()
        if "WAYPOINTS" not in header or "COORDINATES" not in header:
            continue
        for row_number, row in enumerate(table[1:], start=2):
            if len(row) < 2 or row[0].strip().isdigit():
                continue
            ident = _clean_ident(row[0])
            coordinate = _coordinate_pair_from_text(row[1])
            if not ident or coordinate is None:
                continue
            try:
                lat, lon = parse_coordinate_pair(coordinate)
            except CoordinateParseError as error:
                issues.append(
                    Issue("warning", "india-enr44-coordinate", f"row {row_number}: {error}", source_id, ident)
                )
                continue
            points.append(_nav_point(ident, lat, lon, "SIGNIFICANT_POINT", source_id))
    return points


def _parse_route_document(
    html: str,
    document_id: str,
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[Issue],
) -> tuple[list[Airway], list[AirwaySegment]]:
    airways: list[Airway] = []
    segments: list[AirwaySegment] = []
    for table_index, table in enumerate(extract_tables(html), start=1):
        parsed = _parse_route_table(table, table_index, document_id, source_id, point_by_ident, dataset_points, issues)
        if parsed is None:
            continue
        airway, route_segments = parsed
        airways.append(airway)
        segments.extend(route_segments)
    return airways, segments


def _parse_route_table(
    table: list[list[str]],
    table_index: int,
    document_id: str,
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
            _store_point(stored_point, point_by_ident, dataset_points)
        if route_points and route_points[-1].uid == stored_point.uid:
            pending_distance = None
            continue

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
        issues.append(
            Issue(
                "warning",
                "india-route-too-short",
                f"{document_id} table {table_index}: {designator} has fewer than 2 route points",
                source_id,
                airway.uid,
            )
        )
        return None
    return airway, route_segments


def _route_designator(table: list[list[str]]) -> tuple[str | None, str | None]:
    has_route_header = any("ROUTE DESIGNATOR" in " ".join(row).upper() for row in table[:4])
    if not has_route_header:
        return None, None
    for row in table[:10]:
        for cell in row:
            upper = cell.upper()
            if "ROUTE DESIGNATOR" in upper:
                continue
            match = ROUTE_DESIGNATOR_RE.search(upper)
            if match is None:
                continue
            designator = normalize_ident(match.group(1))
            route_type = _route_type_from_cell(cell)
            return designator, route_type
    return None, None


def _route_type_from_cell(cell: str) -> str:
    bracket = re.search(r"\[([A-Z0-9 ]+)\]", cell.upper())
    if bracket:
        return normalize_ident(bracket.group(1))
    rnav = re.search(r"\((RNAV\s*\d+)\)", cell.upper())
    if rnav:
        return normalize_ident(rnav.group(1))
    return "ATS"


def _point_from_row(row: list[str], source_id: str, issues: list[Issue]) -> NavPoint | None:
    text = " ".join(row)
    coordinate_match = list(COORDINATE_PAIR_RE.finditer(text))
    if not coordinate_match:
        return None
    match = coordinate_match[-1]
    coordinate = f"{match.group('lat')} {match.group('lon')}"
    prefix = text[: match.start()]
    ident = _route_ident_from_prefix(prefix)
    if not ident:
        return None
    try:
        lat, lon = parse_coordinate_pair(coordinate)
    except CoordinateParseError as error:
        issues.append(Issue("warning", "india-route-coordinate", str(error), source_id, ident))
        return None
    point_type = "NAVAID" if _looks_like_navaid(prefix) else "SIGNIFICANT_POINT"
    return _nav_point(ident, lat, lon, point_type, source_id)


def _distance_from_row(row: list[str]) -> float | None:
    for cell in row:
        match = re.search(r"(\d+(?:\.\d+)?)\s*NM\b", cell.upper())
        if match:
            return float(match.group(1))
    return None


def _coordinate_pair_from_text(value: str) -> str | None:
    matches = list(COORDINATE_PAIR_RE.finditer(value))
    if not matches:
        return None
    match = matches[-1]
    return f"{match.group('lat')} {match.group('lon')}"


def _route_ident_from_prefix(value: str) -> str:
    upper = value.upper()
    if _looks_like_navaid(upper):
        parenthesized = re.findall(r"\(([A-Z0-9]{2,5})\)", upper)
        if parenthesized:
            return normalize_ident(parenthesized[-1])
    tokens = [normalize_ident(token) for token in re.findall(r"[A-Z0-9]{2,8}", upper)]
    tokens = [token for token in tokens if token and token not in NAVAID_WORDS and token != "FIR"]
    return tokens[-1] if tokens else ""


def _looks_like_navaid(value: str) -> bool:
    upper = value.upper()
    return any(word in upper for word in NAVAID_WORDS)


def _clean_ident(value: str) -> str:
    head = re.split(r"[\s(]", value.strip(), maxsplit=1)[0]
    return normalize_ident(re.sub(r"[^A-Z0-9]", "", head.upper()))


def _store_point(point: NavPoint, point_by_ident: dict[str, NavPoint], dataset_points: list[NavPoint]) -> None:
    if point.ident in point_by_ident:
        return
    point_by_ident[point.ident] = point
    dataset_points.append(point)


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
