from __future__ import annotations

import re
from dataclasses import dataclass

from aviationdb.geo import CoordinateParseError, haversine_nm, initial_bearing_degrees, parse_coordinate_pair
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.hongkong import ClassedRowParser
from aviationdb.parsers.html_table import extract_tables
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

ROW_CLASS_EAIP_SOURCES = {
    "uk",
    "ireland",
    "finland",
    "latvia",
    "czech",
    "estonia",
    "hungary",
    "iceland",
    "poland",
    "cambodia",
    "cocesna",
    "sri_lanka",
    "asecna",
    "uae",
    "oman",
    "saudiarabia",
    "bahrain",
    "qatar",
    "israel",
}
EUROPE_EAIP_SOURCES = ROW_CLASS_EAIP_SOURCES

COORDINATE_PAIR_RE = re.compile(
    r"(?P<lat>\d{6}(?:\.\d+)?[NS]).{0,120}?(?P<lon>\d{7}(?:\.\d+)?[EW])",
    re.IGNORECASE | re.DOTALL,
)
DMS_COORDINATE_PAIR_RE = re.compile(
    r"(?P<lat>\d{1,2}°\s*\d{1,2}['’′]\s*\d{1,2}(?:\.\d+)?[\"'’′″]{0,2}\s*[NS]).{0,160}?"
    r"(?P<lon>\d{1,3}°\s*\d{1,2}['’′]\s*\d{1,2}(?:\.\d+)?[\"'’′″]{0,2}\s*[EW])",
    re.IGNORECASE | re.DOTALL,
)
ROUTE_DESIGNATOR_RE = re.compile(r"\b([A-Z]{1,2}\d{1,4}[A-Z]?)\b")
NAVAID_WORDS = {"DME", "DVOR", "NDB", "TACAN", "VOR", "VOR/DME", "VORTAC"}
ROUTE_HEADER_WORDS = {
    "ROUTE",
    "ROUTES",
    "DESIGNATOR",
    "MARSUUDI",
    "TUNNUS",
    "RNAV",
    "RNP",
}


@dataclass(frozen=True)
class EuropeProfile:
    country: str
    fir: str
    region_code: str = "europe"


PROFILES = {
    "uk": EuropeProfile(country="GB", fir="LONDON"),
    "ireland": EuropeProfile(country="IE", fir="SHANNON"),
    "finland": EuropeProfile(country="FI", fir="HELSINKI"),
    "latvia": EuropeProfile(country="LV", fir="RIGA"),
    "czech": EuropeProfile(country="CZ", fir="PRAGUE"),
    "estonia": EuropeProfile(country="EE", fir="TALLINN"),
    "hungary": EuropeProfile(country="HU", fir="BUDAPEST"),
    "iceland": EuropeProfile(country="IS", fir="REYKJAVIK"),
    "poland": EuropeProfile(country="PL", fir="WARSZAWA"),
    "cambodia": EuropeProfile(country="KH", fir="PHNOM PENH", region_code="asia-southeast"),
    "cocesna": EuropeProfile(country="CS", fir="CENTRAL AMERICA", region_code="central-america"),
    "sri_lanka": EuropeProfile(country="LK", fir="COLOMBO", region_code="south-asia"),
    "asecna": EuropeProfile(country="ASECNA", fir="ASECNA", region_code="africa"),
    "uae": EuropeProfile(country="AE", fir="EMIRATES", region_code="middle-east"),
    "oman": EuropeProfile(country="OM", fir="MUSCAT", region_code="middle-east"),
    "saudiarabia": EuropeProfile(country="SA", fir="JEDDAH", region_code="middle-east"),
    "bahrain": EuropeProfile(country="BH", fir="BAHRAIN", region_code="middle-east"),
    "qatar": EuropeProfile(country="QA", fir="DOHA", region_code="middle-east"),
    "israel": EuropeProfile(country="IL", fir="TEL AVIV", region_code="middle-east"),
}


def parse_europe_eaip_documents(documents: dict[str, str], source_id: str) -> ParsedDataset:
    profile = PROFILES[source_id]
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}

    for document_id, html in documents.items():
        if _looks_like_point_document(document_id):
            for point in _parse_document_points(html, source_id, profile, dataset.issues):
                _store_point(point, point_by_ident, dataset.points)

    for document_id, html in documents.items():
        if not _looks_like_route_document(document_id):
            continue
        airways, segments = _parse_route_document(
            html,
            document_id,
            source_id,
            profile,
            point_by_ident,
            dataset.points,
            dataset.issues,
        )
        dataset.airways.extend(airways)
        dataset.segments.extend(segments)

    return dataset


def _looks_like_point_document(document_id: str) -> bool:
    normalized = document_id.replace("-", "_").lower()
    return "enr_4_1" in normalized or "enr_4_4" in normalized


def _looks_like_route_document(document_id: str) -> bool:
    normalized = document_id.replace("-", "_").lower()
    return "enr_3" in normalized or normalized.startswith("route_")


def _parse_document_points(
    html: str,
    source_id: str,
    profile: EuropeProfile,
    issues: list[Issue],
) -> list[NavPoint]:
    points: list[NavPoint] = []
    for table_index, table in enumerate(extract_tables(html), start=1):
        for row_number, row in enumerate(table, start=1):
            point = _point_from_row(row, source_id, profile, issues)
            if point is not None:
                points.append(point)
            elif _coordinate_pair_from_text(" ".join(row)) is not None:
                issues.append(
                    Issue(
                        "warning",
                        "europe-point-ident-missing",
                        f"table {table_index} row {row_number}: coordinate found without point ident",
                        source_id,
                    )
                )
    return points


def _parse_route_document(
    html: str,
    document_id: str,
    source_id: str,
    profile: EuropeProfile,
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
    pending_point_name: str | None = None

    def flush_route() -> None:
        nonlocal current_airway, current_points, pending_distance, pending_point_name
        if current_airway is None:
            current_points = []
            pending_distance = None
            pending_point_name = None
            return
        if len(current_points) >= 2:
            airways.append(current_airway)
        elif current_points:
            issues.append(
                Issue(
                    "warning",
                    "europe-route-too-short",
                    f"{document_id}: {current_airway.designator} has fewer than 2 points",
                    source_id,
                    current_airway.uid,
                )
            )
        current_airway = None
        current_points = []
        pending_distance = None
        pending_point_name = None

    for row in parser.rows:
        cells = row.cells
        designator, route_type = _route_designator(cells)
        if designator is not None:
            flush_route()
            current_airway = Airway(
                uid=airway_uid(designator, source_id, profile.fir),
                designator=designator,
                route_type=route_type,
                country=profile.country,
                fir=profile.fir,
                source_id=source_id,
            )
            continue

        distance = _distance_from_row(cells)
        if distance is not None:
            pending_distance = distance

        if current_airway is None:
            continue

        point = _route_point_from_row(cells, pending_point_name, source_id, profile, issues)
        if point is None:
            possible_name = _pending_point_name(cells)
            if possible_name:
                pending_point_name = possible_name
            continue

        stored_point = point_by_ident.get(point.ident)
        if stored_point is None:
            stored_point = point
            _store_point(stored_point, point_by_ident, dataset_points)
        if current_points and current_points[-1].uid == stored_point.uid:
            pending_distance = None
            pending_point_name = None
            continue

        if current_points:
            previous = current_points[-1]
            sequence = len(current_points)
            route_distance = pending_distance or haversine_nm(
                (previous.latitude, previous.longitude),
                (stored_point.latitude, stored_point.longitude),
            )
            course = initial_bearing_degrees(
                (previous.latitude, previous.longitude),
                (stored_point.latitude, stored_point.longitude),
            )
            segments.append(
                AirwaySegment(
                    uid=segment_uid(current_airway.uid, sequence, previous.uid, stored_point.uid),
                    airway_uid=current_airway.uid,
                    sequence=sequence,
                    from_point_uid=previous.uid,
                    to_point_uid=stored_point.uid,
                    distance_nm=round(route_distance, 2),
                    initial_course_deg=round(course, 1),
                    reverse_course_deg=round((course + 180) % 360, 1),
                    source_id=source_id,
                )
            )
        current_points.append(stored_point)
        pending_distance = None
        pending_point_name = None

    flush_route()
    return airways, segments


def _route_designator(cells: list[str]) -> tuple[str | None, str | None]:
    if not cells:
        return None, None
    first_cell = _strip_eaip_markers(cells[0]).upper()
    first_match = ROUTE_DESIGNATOR_RE.search(first_cell)
    if first_match and not _coordinate_pair_from_text(first_cell):
        designator = normalize_ident(first_match.group(1))
        if designator not in {"FL", "NM"} and (
            "TXT_DESIG" in cells[0].upper()
            or re.match(r"^\s*[A-Z]{1,2}\d{1,4}[A-Z]?(?:\s*\(|\s|$)", first_cell)
        ):
            if _is_false_route_designator(designator):
                return None, None
            return designator, _route_type_from_text(first_cell)

    joined = _strip_eaip_markers(" ".join(cells)).upper()
    if any(word in joined for word in ROUTE_HEADER_WORDS) and not ROUTE_DESIGNATOR_RE.search(joined):
        return None, None
    if (
        "TXT_DESIG" not in " ".join(cells).upper()
        and "ROUTE_RTE" not in " ".join(cells).upper()
        and not _route_row_shape(cells)
    ):
        return None, None

    match = ROUTE_DESIGNATOR_RE.search(joined)
    if match is None:
        return None, None
    designator = normalize_ident(match.group(1))
    if _is_false_route_designator(designator):
        return None, None
    route_type = _route_type_from_text(joined)
    return designator, route_type


def _is_false_route_designator(designator: str) -> bool:
    return designator in {"FL", "NM"} or re.fullmatch(r"FL\d{2,3}", designator) is not None


def _route_row_shape(cells: list[str]) -> bool:
    if len(cells) > 3:
        return False
    text = _strip_eaip_markers(" ".join(cells)).upper()
    if _coordinate_pair_from_text(text) is not None:
        return False
    if "ROUTE" in text or "RTE" in text:
        return True
    return bool(re.fullmatch(r"\s*[A-Z]{1,2}\d{1,4}[A-Z]?(?:\s*\([^)]+\))?\s*", text))


def _route_type_from_text(text: str) -> str:
    rnav = re.search(r"\bRNAV\s*\d*\b", text)
    if rnav:
        return normalize_ident(rnav.group(0))
    rnp = re.search(r"\bRNP\s*\d*\b", text)
    if rnp:
        return normalize_ident(rnp.group(0))
    return "ATS"


def _route_point_from_row(
    cells: list[str],
    pending_point_name: str | None,
    source_id: str,
    profile: EuropeProfile,
    issues: list[Issue],
) -> NavPoint | None:
    text = " ".join(cells)
    coordinate = _coordinate_pair_from_text(text)
    if coordinate is None:
        return None
    prefix = text[: text.upper().find(coordinate.split()[0].upper())]
    ident_source = prefix if _clean_route_ident(prefix) else pending_point_name or prefix
    ident = _clean_route_ident(ident_source or "")
    if not ident:
        return None
    try:
        lat, lon = parse_coordinate_pair(coordinate)
    except CoordinateParseError as error:
        issues.append(Issue("warning", "europe-route-coordinate", str(error), source_id, ident))
        return None
    point_type = "NAVAID" if _looks_like_navaid(ident_source or "") else "SIGNIFICANT_POINT"
    return _nav_point(ident, lat, lon, point_type, source_id, profile)


def _point_from_row(
    row: list[str],
    source_id: str,
    profile: EuropeProfile,
    issues: list[Issue],
) -> NavPoint | None:
    text = " ".join(row)
    coordinate = _coordinate_pair_from_text(text)
    if coordinate is None:
        return None
    prefix = text[: text.upper().find(coordinate.split()[0].upper())]
    ident = _clean_route_ident(prefix)
    if not ident:
        return None
    try:
        lat, lon = parse_coordinate_pair(coordinate)
    except CoordinateParseError as error:
        issues.append(Issue("warning", "europe-point-coordinate", str(error), source_id, ident))
        return None
    point_type = "NAVAID" if _looks_like_navaid(prefix) else "SIGNIFICANT_POINT"
    return _nav_point(ident, lat, lon, point_type, source_id, profile)


def _coordinate_pair_from_text(value: str) -> str | None:
    match = COORDINATE_PAIR_RE.search(value)
    if match is None:
        cleaned = _strip_eaip_markers(value)
        match = COORDINATE_PAIR_RE.search(cleaned)
        if match is None:
            match = DMS_COORDINATE_PAIR_RE.search(value)
            if match is None:
                match = DMS_COORDINATE_PAIR_RE.search(cleaned)
            if match is None:
                return None
    return f"{match.group('lat')} {match.group('lon')}"


def _distance_from_row(cells: list[str]) -> float | None:
    text = _strip_eaip_markers(" ".join(cells)).upper()
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*NM\b", text)
    if match:
        return float(match.group(1))
    if len(cells) <= 3:
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", text)
        if match:
            return float(match.group(1))
    return None


def _pending_point_name(cells: list[str]) -> str | None:
    text = _strip_eaip_markers(" ".join(cells))
    if _coordinate_pair_from_text(text) is not None or _distance_from_row(cells) is not None:
        return None
    ident = _clean_route_ident(text)
    return text if ident else None


def _clean_route_ident(value: str) -> str:
    cleaned = _strip_eaip_markers(value).upper()
    boundary = re.search(r"\bFIR\s+BDRY\s*\(?([A-Z0-9]{2,8})\)?", cleaned)
    if boundary:
        return normalize_ident(boundary.group(1))
    quoted = re.search(r"'([A-Z0-9]{2,5})'", cleaned)
    if _looks_like_navaid(cleaned) and quoted:
        return normalize_ident(quoted.group(1))
    parenthesized = re.findall(r"\(([A-Z0-9]{2,8})\)", cleaned)
    if _looks_like_navaid(cleaned) and parenthesized:
        return normalize_ident(parenthesized[-1])
    tokens = [normalize_ident(token) for token in re.findall(r"[A-Z][A-Z0-9]{1,7}", cleaned)]
    filtered = [
        token
        for token in tokens
        if token
        and token not in NAVAID_WORDS
        and token not in ROUTE_HEADER_WORDS
        and token not in {"FIR", "BDRY", "NIL", "POINT", "POINTS", "COORDINATES", "REMARKS"}
    ]
    if not filtered:
        return ""
    return filtered[-1] if "FIR BDRY" in cleaned else filtered[0]


def _looks_like_navaid(value: str) -> bool:
    upper = value.upper()
    return any(word in upper for word in NAVAID_WORDS)


def _strip_eaip_markers(value: str) -> str:
    cleaned = re.sub(
        r"T(?:AIRSPACE_LAYER|DESIGNATED_POINT|DME|EN_ROUTE_RTE|NDB|RTE_SEG|TACAN|VOR);[A-Z_]+;\d+",
        " ",
        value,
    )
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _nav_point(ident: str, lat: float, lon: float, point_type: str, source_id: str, profile: EuropeProfile) -> NavPoint:
    return NavPoint(
        uid=point_uid(ident, lat, lon, profile.fir, point_type, source_id),
        ident=ident,
        name=ident,
        latitude=lat,
        longitude=lon,
        point_type=point_type,
        usage_type="ENROUTE",
        country=profile.country,
        fir=profile.fir,
        region_code=profile.region_code,
        source_id=source_id,
    )


def _store_point(point: NavPoint, point_by_ident: dict[str, NavPoint], dataset_points: list[NavPoint]) -> None:
    if point.ident in point_by_ident:
        return
    point_by_ident[point.ident] = point
    dataset_points.append(point)
