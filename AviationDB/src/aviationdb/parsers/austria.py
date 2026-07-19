from __future__ import annotations

import re
from io import BytesIO

from aviationdb.geo import CoordinateParseError, haversine_nm, initial_bearing_degrees, parse_coordinate_pair
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "WIEN"
COUNTRY = "AT"
REGION = "europe"

COORD_RE = re.compile(
    r"(?P<lat>\d{2}\s+\d{2}\s+\d{2}(?:\.\d+)?[NS])\s+"
    r"(?P<lon>\d{3}\s+\d{2}\s+\d{2}(?:\.\d+)?[EW])"
)
ROUTE_HEADER_RE = re.compile(r"(?m)^\s*(?P<designator>[A-Z]{1,3}\d{1,4}[A-Z]?)\s*$")
HEADER_WORDS = {
    "AIP",
    "AIRAC",
    "AMDT",
    "AUSTRIA",
    "BRG",
    "CHANNEL",
    "CLASS",
    "COORDINATES",
    "DIST",
    "DME",
    "ENR",
    "ELEV",
    "FIR",
    "FL",
    "FRA",
    "LOWER",
    "MAG",
    "NAV",
    "NIL",
    "NM",
    "PBN",
    "RCP",
    "RNAV",
    "RNP",
    "ROUTE",
    "UPPER",
    "VOR",
}


def parse_austria_pdf_documents(documents: dict[str, bytes], source_id: str) -> ParsedDataset:
    text_documents = {document_id: _extract_pdf_text(content, document_id) for document_id, content in documents.items()}
    return parse_austria_text_documents(text_documents, source_id)


def parse_austria_text_documents(documents: dict[str, str], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}
    point_by_coord: dict[str, NavPoint] = {}

    for document_id, text in documents.items():
        if document_id == "enr_4_4":
            for point in _parse_enr44_points(text, source_id, dataset.issues):
                _store_point(point, point_by_ident, point_by_coord, dataset.points)

    for document_id, text in documents.items():
        if document_id in {"enr_3_1", "enr_3_2", "enr_3_3"}:
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
        raise RuntimeError("Austria PDF parsing requires the optional pypdf dependency") from error

    reader = PdfReader(BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise ValueError(f"{document_id} PDF did not yield extractable text")
    return text


def _parse_enr44_points(text: str, source_id: str, issues: list[Issue]) -> list[NavPoint]:
    points: list[NavPoint] = []
    for line in text.splitlines():
        match = re.match(r"^\s*(?P<ident>[A-Z][A-Z0-9]{2,6})\s+", line)
        coord = COORD_RE.search(line)
        if match is None or coord is None:
            continue
        ident = normalize_ident(match.group("ident"))
        try:
            lat, lon = parse_coordinate_pair(_coordinate_text(coord))
        except CoordinateParseError as error:
            issues.append(Issue("warning", "austria-enr44-coordinate", str(error), source_id, ident))
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
    headers = [match for match in ROUTE_HEADER_RE.finditer(text) if _is_route_header(text[match.end() : match.end() + 260])]
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
    lines = section.splitlines()
    route_points: list[tuple[NavPoint, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = COORD_RE.fullmatch(line.strip())
        if match is None:
            continue
        point = _route_point_from_coordinate(lines, index, match, source_id, point_by_coord, issues)
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
            issues.append(Issue("warning", "austria-route-too-short", designator, source_id))
        return None

    airway = Airway(
        uid=airway_uid(designator, source_id, FIR),
        designator=designator,
        route_type=_route_type(section),
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
        distance = _distance_between_points(between) or haversine_nm(
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


def _route_point_from_coordinate(
    lines: list[str],
    index: int,
    match: re.Match[str],
    source_id: str,
    point_by_coord: dict[str, NavPoint],
    issues: list[Issue],
) -> NavPoint | None:
    try:
        coordinate = _coordinate_text(match)
        coord_key = _coord_key(coordinate)
    except CoordinateParseError as error:
        issues.append(Issue("warning", "austria-route-coordinate", str(error), source_id))
        return None
    known = point_by_coord.get(coord_key)
    if known is not None:
        return known
    ident = _route_ident_before(lines, index)
    if ident is None:
        return None
    lat, lon = parse_coordinate_pair(coordinate)
    return _nav_point(ident, lat, lon, "SIGNIFICANT_POINT", source_id)


def _route_ident_before(lines: list[str], index: int) -> str | None:
    for offset in range(index - 1, max(-1, index - 5), -1):
        line = lines[offset].strip().upper()
        if not line or COORD_RE.fullmatch(line) or _is_noise_line(line):
            continue
        for candidate in re.findall(r"\b[A-Z][A-Z0-9]{2,6}\b", line):
            if candidate not in HEADER_WORDS:
                return normalize_ident(candidate)
    return None


def _is_route_header(suffix: str) -> bool:
    return COORD_RE.search(suffix) is not None and ("RNAV" in suffix or "RNP" in suffix or "PBN" in suffix)


def _is_noise_line(line: str) -> bool:
    return any(word in line for word in ("EXTREMITY", "TOTAL DIST", "CONTROLLING UNIT", "CHANNEL", "CLASS "))


def _distance_between_points(text: str) -> float | None:
    for line in text.splitlines():
        if "FL" in line or "FT" in line:
            continue
        match = re.search(r"(?<!\d)(\d{1,3}\.\d)\b", line)
        if match is not None:
            distance = float(match.group(1))
            if 0 < distance < 800:
                return distance
    return None


def _route_type(section: str) -> str | None:
    match = re.search(r"\b(RNAV|RNP)\s*([0-9.]+)?\b", section)
    if match is None:
        return "RNAV 5" if "PBN" in section else None
    suffix = f" {match.group(2)}" if match.group(2) else ""
    return f"{match.group(1)}{suffix}"


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


def _nav_point(ident: str, lat: float, lon: float, point_type: str, source_id: str) -> NavPoint:
    return NavPoint(
        uid=point_uid(ident, lat, lon, FIR, point_type, source_id),
        ident=ident,
        latitude=lat,
        longitude=lon,
        point_type=point_type,
        country=COUNTRY,
        fir=FIR,
        region_code=REGION,
        source_id=source_id,
    )


def _coordinate_text(match: re.Match[str]) -> str:
    return f"{match.group('lat')} {match.group('lon')}"


def _coord_key(coordinate: str) -> str:
    lat, lon = parse_coordinate_pair(coordinate)
    return f"{lat:.6f},{lon:.6f}"


def _coord_key_from_point(point: NavPoint) -> str:
    return f"{point.latitude:.6f},{point.longitude:.6f}"
