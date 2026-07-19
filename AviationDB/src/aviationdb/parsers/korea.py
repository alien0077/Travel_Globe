from __future__ import annotations

import re

from aviationdb.geo import CoordinateParseError, haversine_nm, initial_bearing_degrees, parse_coordinate_pair
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.hongkong import ClassedRowParser
from aviationdb.parsers.html_table import extract_tables
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "INCHEON"
COUNTRY = "KR"
REGION = "asia-east"
COORDINATE_PAIR_RE = re.compile(r"\d{6}(?:\.\d+)?[NS]\s*\d{7}(?:\.\d+)?[EW]", re.IGNORECASE)


def parse_korea_eaip_documents(documents: dict[str, str], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}

    for document_id, html in documents.items():
        if document_id == "enr_4_4":
            for point in _parse_enr44_points(html, source_id, dataset.issues):
                point_by_ident.setdefault(point.ident, point)
                dataset.points.append(point)
            continue
        if document_id in {"enr_3_1", "enr_3_3"}:
            airways, segments = _parse_route_document(html, source_id, point_by_ident, dataset.points, dataset.issues)
            dataset.airways.extend(airways)
            dataset.segments.extend(segments)

    return dataset


def _parse_enr44_points(html: str, source_id: str, issues: list[Issue]) -> list[NavPoint]:
    points: list[NavPoint] = []
    for table in extract_tables(html):
        if not table:
            continue
        header = " ".join(table[0]).upper()
        if "NAME-CODE DESIGNATOR" not in header or "CO-ORDINATES" not in header:
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
                    Issue("warning", "korea-enr44-coordinate", f"row {row_number}: {error}", source_id, ident)
                )
                continue
            points.append(_nav_point(ident, lat, lon, "SIGNIFICANT_POINT", source_id))
    return points


def _parse_route_document(
    html: str,
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[Issue],
) -> tuple[list[Airway], list[AirwaySegment]]:
    parser = ClassedRowParser()
    parser.feed(html)

    airways: list[Airway] = []
    segments: list[AirwaySegment] = []
    current_airway: Airway | None = None
    current_points: list[NavPoint] = []
    pending_distance: float | None = None

    def flush_route() -> None:
        nonlocal current_airway, current_points, pending_distance
        if current_airway is not None:
            airways.append(current_airway)
        current_airway = None
        current_points = []
        pending_distance = None

    for row in parser.rows:
        if "AmdtDeleted" in row.row_class:
            continue
        if "Table-row-type-1" in row.row_class:
            designator, route_type = _route_designator(row.cells)
            if designator is None:
                continue
            flush_route()
            current_airway = Airway(
                uid=airway_uid(designator, source_id, FIR),
                designator=designator,
                route_type=route_type,
                country=COUNTRY,
                fir=FIR,
                source_id=source_id,
            )
            continue
        if current_airway is None:
            continue
        if "Table-row-type-3" in row.row_class:
            pending_distance = _distance_from_row(row.cells)
            continue
        if "Table-row-type-2" not in row.row_class:
            continue

        parsed = _route_point_from_row(row.cells, source_id, issues)
        if parsed is None:
            continue
        point = point_by_ident.get(parsed.ident)
        if point is None:
            point = parsed
            point_by_ident[point.ident] = point
            dataset_points.append(point)

        if current_points:
            previous = current_points[-1]
            sequence = len(current_points)
            distance = pending_distance or haversine_nm(
                (previous.latitude, previous.longitude),
                (point.latitude, point.longitude),
            )
            course = initial_bearing_degrees((previous.latitude, previous.longitude), (point.latitude, point.longitude))
            segments.append(
                AirwaySegment(
                    uid=segment_uid(current_airway.uid, sequence, previous.uid, point.uid),
                    airway_uid=current_airway.uid,
                    sequence=sequence,
                    from_point_uid=previous.uid,
                    to_point_uid=point.uid,
                    distance_nm=round(distance, 2),
                    initial_course_deg=round(course, 1),
                    reverse_course_deg=round((course + 180) % 360, 1),
                    source_id=source_id,
                )
            )
        current_points.append(point)
        pending_distance = None

    flush_route()
    return airways, segments


def _route_designator(cells: list[str]) -> tuple[str | None, str | None]:
    if not cells or cells[0].upper().startswith("ROUTE DESIGNATOR"):
        return None, None
    cell = cells[0].strip()
    match = re.match(r"^([A-Z]\d{1,4}[A-Z]?)\*?\s*(?:\(([^)]+)\))?$", cell.upper())
    if match is None:
        return None, None
    return normalize_ident(match.group(1)), normalize_ident(match.group(2) or "ATS")


def _route_point_from_row(cells: list[str], source_id: str, issues: list[Issue]) -> NavPoint | None:
    if len(cells) < 3 or "SIGNIFICANT POINT" in " ".join(cells).upper():
        return None
    ident = _clean_route_ident(cells[1])
    coordinates = cells[2].strip()
    if not ident or not coordinates:
        return None
    if COORDINATE_PAIR_RE.search(coordinates) is None:
        if "UNKNOWN REFERENCE" not in cells[1].upper():
            issues.append(
                Issue("warning", "korea-route-coordinate-missing", f"{ident}: {coordinates}", source_id, ident)
            )
        return None
    try:
        lat, lon = parse_coordinate_pair(coordinates)
    except CoordinateParseError as error:
        issues.append(Issue("warning", "korea-route-coordinate", str(error), source_id, ident))
        return None
    is_navaid = "(" in cells[1] and any(token in cells[1].upper() for token in ["VOR", "DME", "NDB"])
    point_type = "NAVAID" if is_navaid else "SIGNIFICANT_POINT"
    return _nav_point(ident, lat, lon, point_type, source_id)


def _distance_from_row(cells: list[str]) -> float | None:
    for cell in cells:
        if cell.upper().startswith(("TRACK", "INITIAL TRACK", "DIST", "GREAT CIRCLE", "↓", "UPPER LIMIT")):
            continue
        match = re.fullmatch(r"\d+(?:\.\d+)?", cell.strip())
        if match:
            return float(match.group(0))
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
