from __future__ import annotations

import re
from io import BytesIO

from aviationdb.geo import CoordinateParseError, haversine_nm, initial_bearing_degrees, parse_coordinate_pair
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "FRANCE"
COUNTRY = "FR"
REGION = "europe"

LAT_DMS = r"\d{2}\s*[°º]\s*\d{2}\s*['’]\s*\d{2}(?:\.\d+)?\s*\"?\s*[NS]"
LON_DMS = r"\d{3}\s*[°º]\s*\d{2}\s*['’]\s*\d{2}(?:\.\d+)?\s*\"?\s*[EW]"
COORD_PAIR_RE = re.compile(rf"(?P<lat>{LAT_DMS})\s*(?P<lon>{LON_DMS})")
ROUTE_HEADER_RE = re.compile(r"(?m)(?:^|[\n|])\s*(?P<designator>[A-Z]{1,2}\d{1,4}[A-Z]?)\s*(?=$|[\n|])")
HEADER_WORDS = {
    "AIP",
    "AIRAC",
    "AMDT",
    "AMSL",
    "ATS",
    "COORDINATES",
    "CONTROL",
    "DESIGNATION",
    "DIST",
    "DME",
    "ENR",
    "FL",
    "FRA",
    "FRANCE",
    "MAG",
    "MOCA",
    "NDB",
    "RNAV",
    "ROUTE",
    "SERVICE",
    "SIGNIFICANT",
    "VOR",
}
NAVAID_WORDS = {"DME", "NDB", "VOR", "VOR-DME", "VOR/DME", "VORTAC"}


def parse_france_pdf_documents(documents: dict[str, bytes], source_id: str) -> ParsedDataset:
    text_documents: dict[str, str] = {}
    for document_id, content in documents.items():
        text_documents[document_id] = _extract_pdf_text(content, document_id)
    return parse_france_text_documents(text_documents, source_id)


def parse_france_text_documents(documents: dict[str, str], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}
    point_by_coord: dict[str, NavPoint] = {}

    for document_id, text in documents.items():
        if document_id == "enr_4_4":
            for point in _parse_enr44_points(text, source_id, dataset.issues):
                _store_point(point, point_by_ident, point_by_coord, dataset.points)

    for document_id, text in documents.items():
        if document_id == "enr_3_2":
            airways, segments = _parse_route_text(
                text,
                source_id,
                point_by_ident,
                point_by_coord,
                dataset.points,
                dataset.issues,
            )
            dataset.airways.extend(airways)
            dataset.segments.extend(segments)

    return dataset


def _extract_pdf_text(content: bytes, document_id: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - depends on runtime packaging
        raise RuntimeError("France PDF parsing requires the optional pypdf dependency") from error

    reader = PdfReader(BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages)
    if not text.strip():
        raise ValueError(f"{document_id} PDF did not yield extractable text")
    return text


def _parse_enr44_points(text: str, source_id: str, issues: list[Issue]) -> list[NavPoint]:
    points: list[NavPoint] = []
    for match in COORD_PAIR_RE.finditer(text):
        ident = _ident_after_coordinate(text[match.end() : match.end() + 100])
        if ident is None:
            continue
        coordinate = _coordinate_text(match)
        try:
            lat, lon = parse_coordinate_pair(coordinate)
        except CoordinateParseError as error:
            issues.append(Issue("warning", "france-enr44-coordinate", str(error), source_id, ident))
            continue
        points.append(_nav_point(ident, lat, lon, "SIGNIFICANT_POINT", source_id))
    return points


def _parse_route_text(
    text: str,
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    point_by_coord: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[Issue],
) -> tuple[list[Airway], list[AirwaySegment]]:
    airways: list[Airway] = []
    segments: list[AirwaySegment] = []
    headers = [
        match
        for match in ROUTE_HEADER_RE.finditer(text)
        if not _is_false_designator(match.group("designator"))
    ]
    for index, header in enumerate(headers):
        start = header.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        designator = normalize_ident(header.group("designator"))
        parsed = _parse_route_section(
            designator,
            text[start:end],
            source_id,
            point_by_ident,
            point_by_coord,
            dataset_points,
            issues,
        )
        if parsed is None:
            continue
        airway, route_segments = parsed
        airways.append(airway)
        segments.extend(route_segments)
    return airways, segments


def _parse_route_section(
    designator: str,
    section: str,
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    point_by_coord: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[Issue],
) -> tuple[Airway, list[AirwaySegment]] | None:
    route_points: list[tuple[NavPoint, re.Match[str]]] = []
    for match in COORD_PAIR_RE.finditer(section):
        point = _point_from_route_match(section, match, source_id, point_by_coord, issues)
        if point is None:
            continue
        stored = point_by_ident.get(point.ident)
        if stored is None:
            stored = point
            _store_point(stored, point_by_ident, point_by_coord, dataset_points)
        if route_points and route_points[-1][0].uid == stored.uid:
            continue
        route_points.append((stored, match))

    if len(route_points) < 2:
        if route_points:
            issues.append(Issue("warning", "france-route-too-short", designator, source_id))
        return None

    airway = Airway(
        uid=airway_uid(designator, source_id, FIR),
        designator=designator,
        route_type="RNAV 5",
        country=COUNTRY,
        fir=FIR,
        source_id=source_id,
    )
    route_segments: list[AirwaySegment] = []
    for sequence, ((from_point, from_match), (to_point, to_match)) in enumerate(
        zip(route_points, route_points[1:], strict=False),
        start=1,
    ):
        between = section[from_match.end() : to_match.start()]
        distance = _distance_after_point(between) or haversine_nm(
            (from_point.latitude, from_point.longitude),
            (to_point.latitude, to_point.longitude),
        )
        course = initial_bearing_degrees(
            (from_point.latitude, from_point.longitude),
            (to_point.latitude, to_point.longitude),
        )
        route_segments.append(
            AirwaySegment(
                uid=segment_uid(airway.uid, sequence, from_point.uid, to_point.uid),
                airway_uid=airway.uid,
                sequence=sequence,
                from_point_uid=from_point.uid,
                to_point_uid=to_point.uid,
                distance_nm=round(distance, 2),
                initial_course_deg=round(course, 1),
                reverse_course_deg=round((course + 180) % 360, 1),
                source_id=source_id,
            )
        )
    return airway, route_segments


def _point_from_route_match(
    section: str,
    match: re.Match[str],
    source_id: str,
    point_by_coord: dict[str, NavPoint],
    issues: list[Issue],
) -> NavPoint | None:
    coordinate = _coordinate_text(match)
    try:
        coord_key = _coord_key(coordinate)
    except CoordinateParseError as error:
        issues.append(Issue("warning", "france-route-coordinate", str(error), source_id))
        return None
    known = point_by_coord.get(coord_key)
    if known is not None:
        return known
    suffix = section[match.end() : match.end() + 160]
    ident = _navaid_ident_after_coordinate(suffix) or _ident_after_coordinate(suffix)
    if ident is None:
        return None
    lat, lon = parse_coordinate_pair(coordinate)
    point_type = "NAVAID" if _navaid_ident_after_coordinate(suffix) else "SIGNIFICANT_POINT"
    return _nav_point(ident, lat, lon, point_type, source_id)


def _store_point(
    point: NavPoint,
    point_by_ident: dict[str, NavPoint],
    point_by_coord: dict[str, NavPoint],
    dataset_points: list[NavPoint],
) -> None:
    if point.ident in point_by_ident:
        return
    point_by_ident[point.ident] = point
    point_by_coord[_coord_key_from_point(point)] = point
    dataset_points.append(point)


def _ident_after_coordinate(suffix: str) -> str | None:
    stop = _point_label_stop(suffix)
    candidates = re.findall(r"\b[A-Z][A-Z0-9]{2,6}\b", suffix[:stop].upper())
    for candidate in reversed(candidates):
        if candidate not in HEADER_WORDS and candidate not in NAVAID_WORDS:
            return normalize_ident(candidate)
    return None


def _navaid_ident_after_coordinate(suffix: str) -> str | None:
    stop = _point_label_stop(suffix)
    matches = re.findall(r"\(\s*([A-Z0-9]{2,5})\s*\)", suffix[:stop].upper())
    for candidate in matches:
        if candidate not in {"NM", "FL"}:
            return normalize_ident(candidate)
    return None


def _point_label_stop(suffix: str) -> int:
    marker_stops = [position for marker in ("▲", "∆") if (position := suffix.find(marker)) >= 0]
    if marker_stops:
        return min(marker_stops)
    field_stops = [position for marker in ("|", "\n") if (position := suffix.find(marker)) >= 0]
    return min(field_stops) if field_stops else len(suffix)


def _distance_after_point(text: str) -> float | None:
    compact = text.replace(" ", "")
    fl_packed_match = re.search(r"FL\d{3}(?P<distance>\d{1,3}\.\d)\d{0,6}RNAV", compact)
    if fl_packed_match is not None:
        return float(fl_packed_match.group("distance"))
    rnav_match = re.search(r"(?<!\d)(?P<distance>\d{1,3}\.\d)\d{0,6}RNAV", compact)
    if rnav_match is not None:
        return float(rnav_match.group("distance"))
    for value in re.findall(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*NM\b", text.upper()):
        distance = float(value)
        if 0 < distance < 800:
            return distance
    for value in re.findall(r"(?<!\d)(\d{1,3}\.\d)(?!\d)", text):
        distance = float(value)
        if 0 < distance < 800:
            return distance
    return None


def _coordinate_text(match: re.Match[str]) -> str:
    return f"{_normalize_dms(match.group('lat'))} {_normalize_dms(match.group('lon'))}"


def _normalize_dms(text: str) -> str:
    return text.replace("º", "°").replace("’", "'").replace(" ", "")


def _coord_key(coordinate: str) -> str:
    lat, lon = parse_coordinate_pair(coordinate)
    return f"{lat:.7f},{lon:.7f}"


def _coord_key_from_point(point: NavPoint) -> str:
    return f"{point.latitude:.7f},{point.longitude:.7f}"


def _nav_point(ident: str, lat: float, lon: float, point_type: str, source_id: str) -> NavPoint:
    normalized = normalize_ident(ident)
    return NavPoint(
        uid=point_uid(normalized, lat, lon, FIR, point_type, source_id),
        ident=normalized,
        latitude=round(lat, 7),
        longitude=round(lon, 7),
        point_type=point_type,
        source_id=source_id,
        country=COUNTRY,
        fir=FIR,
        region_code=REGION,
    )


def _is_false_designator(designator: str) -> bool:
    normalized = normalize_ident(designator)
    return normalized.startswith(("AD", "AIRAC", "AMDT", "ENR", "FL", "GEN", "RNAV"))
