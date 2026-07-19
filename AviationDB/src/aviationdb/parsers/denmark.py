from __future__ import annotations

import re
from io import BytesIO

from aviationdb.geo import CoordinateParseError, haversine_nm, initial_bearing_degrees, parse_coordinate_pair
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "COPENHAGEN"
COUNTRY = "DK"
REGION = "europe"

COORD_RE = re.compile(r"(?P<lat>\d{6}(?:\.\d+)?[NS])\s+(?P<lon>\d{7}(?:\.\d+)?[EW])")
ROUTE_HEADER_RE = re.compile(r"(?m)^\s*(?P<designator>[A-Z]{1,3}\d{1,4}[A-Z]?)\s*$")
TRACK_RE = re.compile(r"\d{3}\s*°\s*/\s*\d{3}\s*°")
HEADER_WORDS = {
    "AIP",
    "AIRAC",
    "AMDT",
    "AVBL",
    "BDRY",
    "CHANNEL",
    "CLASS",
    "COP",
    "DENMARK",
    "DIST",
    "DME",
    "DOC",
    "ELEV",
    "ENR",
    "EXTREMITY",
    "FIR",
    "FL",
    "FRA",
    "H24",
    "INFO",
    "MHZ",
    "NAVIAIR",
    "NIL",
    "NM",
    "RNAV",
    "RNP",
    "ROUTE",
    "TACAN",
    "TOTAL",
    "VOR",
}
NAVAID_WORDS = {"DME", "TACAN", "VOR", "VOR/DME"}


def parse_denmark_pdf_documents(documents: dict[str, bytes], source_id: str) -> ParsedDataset:
    text_documents: dict[str, str] = {}
    for document_id, content in documents.items():
        text_documents[document_id] = _extract_pdf_text(content, document_id)
    return parse_denmark_text_documents(text_documents, source_id)


def parse_denmark_text_documents(documents: dict[str, str], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}
    point_by_coord: dict[str, NavPoint] = {}

    for document_id, text in documents.items():
        if document_id == "enr_4_4":
            for point in _parse_enr44_points(text, source_id, dataset.issues):
                _store_point(point, point_by_ident, point_by_coord, dataset.points)
        elif document_id == "enr_4_1":
            for point in _parse_enr41_navaids(text, source_id, dataset.issues):
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
        raise RuntimeError("Denmark PDF parsing requires the optional pypdf dependency") from error

    reader = PdfReader(BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise ValueError(f"{document_id} PDF did not yield extractable text")
    return text


def _parse_enr44_points(text: str, source_id: str, issues: list[Issue]) -> list[NavPoint]:
    points: list[NavPoint] = []
    for line in text.splitlines():
        match = re.match(
            r"^\s*(?P<ident>[A-Z][A-Z0-9]{2,6})\s+"
            r"(?P<lat>\d{6}(?:\.\d+)?[NS])\s+(?P<lon>\d{7}(?:\.\d+)?[EW])\b",
            line,
        )
        if match is None:
            continue
        ident = normalize_ident(match.group("ident"))
        try:
            lat, lon = parse_coordinate_pair(_coordinate_text(match))
        except CoordinateParseError as error:
            issues.append(Issue("warning", "denmark-enr44-coordinate", str(error), source_id, ident))
            continue
        points.append(_nav_point(ident, lat, lon, "SIGNIFICANT_POINT", source_id))
    return points


def _parse_enr41_navaids(text: str, source_id: str, issues: list[Issue]) -> list[NavPoint]:
    points: list[NavPoint] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = COORD_RE.fullmatch(line.strip())
        if match is None:
            continue
        ident = _navaid_ident_before(lines, index)
        if ident is None:
            continue
        try:
            lat, lon = parse_coordinate_pair(_coordinate_text(match))
        except CoordinateParseError as error:
            issues.append(Issue("warning", "denmark-enr41-coordinate", str(error), source_id, ident))
            continue
        points.append(_nav_point(ident, lat, lon, "NAVAID", source_id))
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
        if _is_route_header(text[match.end() : match.end() + 80])
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
    lines = section.splitlines()
    route_points: list[NavPoint] = []
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
        if route_points and route_points[-1].uid == stored.uid:
            continue
        route_points.append(stored)

    if len(route_points) < 2:
        if route_points:
            issues.append(Issue("warning", "denmark-route-too-short", designator, source_id))
        return None

    airway = Airway(
        uid=airway_uid(designator, source_id, FIR),
        designator=designator,
        route_type=_route_type(section),
        country=COUNTRY,
        fir=FIR,
        source_id=source_id,
    )
    official_distances = _segment_distances(section)
    route_segments: list[AirwaySegment] = []
    for sequence, (from_point, to_point) in enumerate(zip(route_points, route_points[1:], strict=False), start=1):
        distance = (
            official_distances[sequence - 1]
            if sequence - 1 < len(official_distances)
            else haversine_nm((from_point.latitude, from_point.longitude), (to_point.latitude, to_point.longitude))
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
        issues.append(Issue("warning", "denmark-route-coordinate", str(error), source_id))
        return None
    known = point_by_coord.get(coord_key)
    if known is not None:
        return known
    ident, point_type = _route_ident_before(lines, index)
    if ident is None:
        return None
    lat, lon = parse_coordinate_pair(coordinate)
    return _nav_point(ident, lat, lon, point_type, source_id)


def _route_ident_before(lines: list[str], index: int) -> tuple[str | None, str]:
    for offset in range(index - 1, max(-1, index - 6), -1):
        line = lines[offset].strip()
        if not line or COORD_RE.fullmatch(line):
            continue
        parenthesized = re.fullmatch(r"\(([A-Z0-9]{2,5})\)", line)
        if parenthesized is not None:
            return normalize_ident(parenthesized.group(1)), "NAVAID"
        if _is_noise_line(line):
            continue
        parenthesized = re.search(r"\(([A-Z0-9]{2,5})\)", line)
        if parenthesized is not None:
            return normalize_ident(parenthesized.group(1)), "NAVAID"
        for candidate in re.findall(r"\b[A-Z][A-Z0-9]{2,6}\b", line.upper()):
            if candidate not in HEADER_WORDS and candidate not in NAVAID_WORDS:
                return normalize_ident(candidate), "SIGNIFICANT_POINT"
    return None, "SIGNIFICANT_POINT"


def _navaid_ident_before(lines: list[str], index: int) -> str | None:
    prefix = "\n".join(lines[max(0, index - 12) : index]).upper()
    for candidate in reversed(re.findall(r"\b[A-Z][A-Z0-9]{1,4}\b", prefix)):
        if candidate not in HEADER_WORDS and candidate not in NAVAID_WORDS and not candidate.startswith("CH"):
            return normalize_ident(candidate)
    return None


def _segment_distances(section: str) -> list[float]:
    lines = section.splitlines()
    distances: list[float] = []
    for index, line in enumerate(lines):
        if "Total DIST" in line:
            break
        if TRACK_RE.search(line):
            for candidate_line in [line, *lines[index + 1 : index + 4]]:
                match = re.search(r"(?<!FL\s)(?<!CH\s)(?<!\d)(\d{1,3}\.\d)\b", candidate_line)
                if match is not None:
                    distance = float(match.group(1))
                    if 0 < distance < 800:
                        distances.append(distance)
                        break
    return distances


def _route_type(section: str) -> str | None:
    match = re.search(r"\(\s*(RNAV|RNP)\s*([0-9.]+)\s*\)", section)
    if match is None:
        return None
    return f"{match.group(1)} {match.group(2)}"


def _is_route_header(suffix: str) -> bool:
    return "RNAV" in suffix or "RNP" in suffix


def _is_noise_line(line: str) -> bool:
    upper = line.upper()
    return any(word in upper for word in ("EXTREMITY", "TOTAL DIST", "CONTROLLING UNIT", "CHANNEL", "CLASS "))


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
    return f"{lat:.7f},{lon:.7f}"


def _coord_key_from_point(point: NavPoint) -> str:
    return f"{point.latitude:.7f},{point.longitude:.7f}"
