from __future__ import annotations

import re
from io import BytesIO

from aviationdb.geo import CoordinateParseError, haversine_nm, initial_bearing_degrees, parse_coordinate_pair
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "KUALA_LUMPUR_KOTA_KINABALU"
COUNTRY = "MY"
REGION = "asia-southeast"

COORD_RE = re.compile(
    r"(?P<lat>\d{2}\s?\d{2}\s?\d{2}(?:\.\d+)?N)\s+"
    r"(?P<lon>\d{3}\s?\d{2}\s?\d{2}(?:\.\d+)?E)",
    re.IGNORECASE,
)
DESIGNATOR_LINE_RE = re.compile(r"(?m)^\s*(?P<designator>[A-Z][0-9]{1,4}[A-Z]?)\s*$")
HEADER_WORDS = {
    "AIP",
    "ALT",
    "AMDT",
    "AND",
    "AUTHORITY",
    "BDRY",
    "CLASSIFICATION",
    "CONTROLLING",
    "COORDINATES",
    "CRUISING",
    "DEPARTMENT",
    "DESIGNATOR",
    "DIST",
    "EVEN",
    "FL",
    "FLIGHT",
    "JOINIG",
    "JOINING",
    "LIMITS",
    "LINTANG",
    "LOWER",
    "MAG",
    "MALAYSIA",
    "MINIMUM",
    "NM",
    "ODD",
    "POINTS",
    "REFER",
    "REMARKS",
    "ROUTE",
    "SIGNIFICANT",
    "TRACK",
    "TOWN",
    "UPPER",
    "WGS84",
}


def parse_malaysia_pdf_documents(documents: dict[str, bytes], source_id: str) -> ParsedDataset:
    text_documents: dict[str, str] = {}
    for document_id, content in documents.items():
        text_documents[document_id] = _extract_pdf_text(content, document_id)
    return parse_malaysia_text_documents(text_documents, source_id)


def parse_malaysia_text_documents(documents: dict[str, str], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}
    point_by_coord: dict[str, NavPoint] = {}

    for document_id, text in documents.items():
        if document_id == "enr_4_3":
            points = _parse_enr43_points(text, source_id, dataset.issues)
            for point in points:
                _store_point(point, point_by_ident, point_by_coord, dataset.points)

    for document_id, text in documents.items():
        if document_id in {"enr_3_1", "enr_3_3", "enr_3_5"}:
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
        raise RuntimeError("Malaysia PDF parsing requires the optional pypdf dependency") from error

    reader = PdfReader(BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages)
    if not text.strip():
        raise ValueError(f"{document_id} PDF did not yield extractable text")
    return text


def _parse_enr43_points(text: str, source_id: str, issues: list[Issue]) -> list[NavPoint]:
    points: list[NavPoint] = []
    for match in COORD_RE.finditer(text):
        ident = _ident_before(text[: match.start()])
        if not ident:
            continue
        coordinate = _coordinate_text(match)
        try:
            lat, lon = parse_coordinate_pair(coordinate)
        except CoordinateParseError as error:
            issues.append(Issue("warning", "malaysia-enr43-coordinate", str(error), source_id, ident))
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
    matches = list(DESIGNATOR_LINE_RE.finditer(text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        designator = normalize_ident(match.group("designator"))
        if _is_false_designator(designator):
            continue
        section = text[start:end]
        parsed = _parse_route_section(
            designator,
            section,
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
    airway = Airway(
        uid=airway_uid(designator, source_id, FIR),
        designator=designator,
        route_type="ATS",
        country=COUNTRY,
        fir=FIR,
        source_id=source_id,
    )
    route_points: list[tuple[NavPoint, re.Match[str]]] = []
    for match in COORD_RE.finditer(section):
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
            issues.append(Issue("warning", "malaysia-route-too-short", designator, source_id))
        return None

    route_segments: list[AirwaySegment] = []
    for sequence, ((from_point, from_match), (to_point, to_match)) in enumerate(
        zip(route_points, route_points[1:], strict=False),
        start=1,
    ):
        between = section[from_match.end() : to_match.start()]
        distance = _distance_from_text(between) or haversine_nm(
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
        issues.append(Issue("warning", "malaysia-route-coordinate", str(error), source_id))
        return None
    known = point_by_coord.get(coord_key)
    if known is not None:
        return known
    prefix = section[max(0, match.start() - 260) : match.start()]
    ident = _navaid_ident_before(prefix) or _ident_before(prefix)
    if not ident:
        return None
    lat, lon = parse_coordinate_pair(coordinate)
    point_type = "NAVAID" if _navaid_ident_before(prefix) else "SIGNIFICANT_POINT"
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


def _ident_before(prefix: str) -> str | None:
    candidates = re.findall(r"\b[A-Z][A-Z0-9]{2,6}\b", prefix[-120:].upper())
    for candidate in reversed(candidates):
        if candidate not in HEADER_WORDS and not re.fullmatch(r"FL\d+", candidate):
            return normalize_ident(candidate)
    return None


def _navaid_ident_before(prefix: str) -> str | None:
    matches = re.findall(r"\(([A-Z0-9]{2,5})\)", prefix.upper())
    for candidate in reversed(matches):
        if candidate not in {"P", "S", "NM", "ALT", "FIR"}:
            return normalize_ident(candidate)
    return None


def _distance_from_text(text: str) -> float | None:
    candidates = [float(value) for value in re.findall(r"(\d+(?:\.\d+)?)\s*NM\b", text.upper())]
    candidates = [value for value in candidates if 0 < value < 800]
    return candidates[0] if candidates else None


def _coordinate_text(match: re.Match[str]) -> str:
    lat = match.group("lat").replace(" ", "")
    lon = match.group("lon").replace(" ", "")
    return f"{lat} {lon}"


def _coord_key(coordinate: str) -> str:
    lat, lon = parse_coordinate_pair(coordinate)
    return f"{lat:.7f},{lon:.7f}"


def _coord_key_from_point(point: NavPoint) -> str:
    return f"{point.latitude:.7f},{point.longitude:.7f}"


def _is_false_designator(designator: str) -> bool:
    return designator.startswith(("ENR", "GEN", "AD"))


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
