from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any, cast

from aviationdb.geo import haversine_nm, initial_bearing_degrees
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

COUNTRY = "CL"
FIR = "SANTIAGO"
REGION = "south-america"
MAX_SEGMENT_NM = 900.0

ROUTE_RE = re.compile(r"\b(?P<prefix>[A-Z]{1,2})\s+(?P<number>\d{1,4}[A-Z]?)\b")
ROUTE_PREFIXES = {"A", "B", "G", "L", "M", "N", "Q", "R", "T", "V", "W", "UL", "UM", "UN", "UP", "UQ", "UT", "UV", "UW"}
COORD_PAIR_RE = re.compile(
    r"(?P<lat_deg>\d{1,2})°\s*(?P<lat_min>\d{1,2})'\s*(?P<lat_sec>\d{1,2}(?:\.\d+)?)''?\s*(?P<lat_hemi>[NS])"
    r"\s+"
    r"(?P<lon_deg>\d{1,3})°\s*(?P<lon_min>\d{1,2})'\s*(?P<lon_sec>\d{1,2}(?:\.\d+)?)''?\s*(?P<lon_hemi>[EW])"
)

STOPWORDS = {
    "ACC",
    "ACCI",
    "ACCN",
    "ACCS",
    "AIP",
    "AIS",
    "AMDT",
    "APP",
    "CHG",
    "CHILE",
    "CONV",
    "CTLU",
    "DCL",
    "DIST",
    "DME",
    "EVEN",
    "FL",
    "FORMATO",
    "LAYOUT",
    "LIMITS",
    "MAG",
    "NAV",
    "NM",
    "ODD",
    "QNH",
    "RMK",
    "RNAV",
    "RNP",
    "ROUTE",
    "SCDA",
    "SCFA",
    "SCCI",
    "SCQP",
    "TR",
    "VOLUMEN",
    "VOR",
    "WAYPOINT",
}


@dataclass(frozen=True)
class _Block:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def y_center(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(frozen=True)
class _RoutePoint:
    route: str
    nav_point: NavPoint
    route_type: str | None


def parse_chile_pdf_documents(documents: dict[str, bytes], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    points_by_uid: dict[str, NavPoint] = {}
    route_points: dict[str, list[_RoutePoint]] = {}
    route_types: dict[str, str] = {}

    for document_id, content in sorted(documents.items()):
        if not _is_route_document(document_id):
            continue
        blocks_by_page = _extract_pdf_blocks(content, document_id)
        for page_blocks in blocks_by_page:
            for route_point in _parse_page_route_points(page_blocks, source_id, dataset.issues):
                points_by_uid.setdefault(route_point.nav_point.uid, route_point.nav_point)
                route_points.setdefault(route_point.route, []).append(route_point)
                if route_point.route_type:
                    route_types[route_point.route] = route_point.route_type

    dataset.points.extend(sorted(points_by_uid.values(), key=lambda point: (point.ident, point.uid)))
    for route, points in sorted(route_points.items()):
        unique_points = _drop_consecutive_duplicates(points)
        if len(unique_points) < 2:
            dataset.issues.append(Issue("warning", "chile-route-too-short", route, source_id))
            continue
        route_uid = airway_uid(route, source_id, FIR)
        dataset.airways.append(
            Airway(
                uid=route_uid,
                designator=route,
                source_id=source_id,
                route_type=route_types.get(route),
                country=COUNTRY,
                fir=FIR,
            )
        )
        sequence = 1
        for left, right in zip(unique_points, unique_points[1:], strict=False):
            distance_nm = haversine_nm(
                (left.nav_point.latitude, left.nav_point.longitude),
                (right.nav_point.latitude, right.nav_point.longitude),
            )
            if distance_nm < 0.5:
                continue
            if distance_nm > MAX_SEGMENT_NM:
                dataset.issues.append(
                    Issue(
                        "warning",
                        "chile-segment-long-distance",
                        f"{route}: {left.nav_point.ident}->{right.nav_point.ident} is {distance_nm:.1f} NM",
                        source_id,
                    )
                )
                continue
            dataset.segments.append(
                AirwaySegment(
                    uid=segment_uid(route_uid, sequence, left.nav_point.uid, right.nav_point.uid),
                    airway_uid=route_uid,
                    sequence=sequence,
                    from_point_uid=left.nav_point.uid,
                    to_point_uid=right.nav_point.uid,
                    source_id=source_id,
                    distance_nm=round(distance_nm, 2),
                    initial_course_deg=round(
                        initial_bearing_degrees(
                            (left.nav_point.latitude, left.nav_point.longitude),
                            (right.nav_point.latitude, right.nav_point.longitude),
                        ),
                        1,
                    ),
                    reverse_course_deg=round(
                        initial_bearing_degrees(
                            (right.nav_point.latitude, right.nav_point.longitude),
                            (left.nav_point.latitude, left.nav_point.longitude),
                        ),
                        1,
                    ),
                )
            )
            sequence += 1

    return dataset


def _is_route_document(document_id: str) -> bool:
    lowered = document_id.lower()
    return ("enr_3" in lowered or "enr 3" in lowered) and (
        "convencional" in lowered or "rnav" in lowered
    )


def _extract_pdf_blocks(content: bytes, document_id: str) -> list[list[_Block]]:
    try:
        fitz = cast(Any, importlib.import_module("fitz"))
    except ImportError as error:  # pragma: no cover - depends on runtime packaging
        raise RuntimeError("Chile PDF parsing requires the optional PyMuPDF dependency") from error

    blocks_by_page: list[list[_Block]] = []
    with fitz.open(stream=BytesIO(content), filetype="pdf") as document:
        for page_index, page in enumerate(document):
            blocks = []
            for raw_block in page.get_text("blocks", sort=True):
                x0, y0, x1, y1, text = raw_block[:5]
                clean_text = _clean_text(str(text))
                if clean_text:
                    blocks.append(
                        _Block(
                            page=page_index,
                            x0=float(x0),
                            y0=float(y0),
                            x1=float(x1),
                            y1=float(y1),
                            text=clean_text,
                        )
                    )
            if not blocks:
                raise ValueError(f"{document_id} page {page_index + 1} did not yield extractable text blocks")
            blocks_by_page.append(sorted(blocks, key=lambda block: (block.y0, block.x0)))
    return blocks_by_page


def _parse_page_route_points(blocks: list[_Block], source_id: str, issues: list[Issue]) -> list[_RoutePoint]:
    route_points: list[_RoutePoint] = []
    current_route: str | None = None
    current_route_type: str | None = None

    for block in blocks:
        block_without_coordinates = COORD_PAIR_RE.sub(" ", block.text)
        route_match = _find_route(block_without_coordinates)
        if route_match is not None and coord_match_is_absent(block.text):
            current_route = _normalize_route(route_match)
            current_route_type = _route_type(block.text)

        coord_match = COORD_PAIR_RE.search(block.text)
        if coord_match is None:
            continue

        row_blocks = _nearby_row_blocks(blocks, block)
        row_text = _clean_text(" ".join(item.text for item in row_blocks))
        row_without_coordinates = COORD_PAIR_RE.sub(" ", row_text)
        route_match = _find_route(row_without_coordinates)
        if route_match is not None:
            current_route = _normalize_route(route_match)
        row_route_type = _route_type(row_text) or current_route_type
        if row_route_type:
            current_route_type = row_route_type

        if current_route is None:
            issues.append(Issue("warning", "chile-route-missing", row_text[:160], source_id))
            continue

        ident = _extract_ident(row_blocks, block)
        if ident is None:
            issues.append(Issue("warning", "chile-ident-missing", f"{current_route}: {row_text[:160]}", source_id))
            continue

        latitude, longitude = _coordinate_from_match(coord_match)
        point_type = "NAVAID" if "VOR/DME" in row_text or " VOR " in row_text else "WAYPOINT"
        route_points.append(
            _RoutePoint(
                route=current_route,
                nav_point=NavPoint(
                    uid=point_uid(ident, latitude, longitude, FIR, point_type, source_id),
                    ident=ident,
                    latitude=latitude,
                    longitude=longitude,
                    point_type=point_type,
                    source_id=source_id,
                    country=COUNTRY,
                    fir=FIR,
                    region_code=REGION,
                ),
                route_type=row_route_type,
            )
        )

    return route_points


def _nearby_row_blocks(blocks: list[_Block], coordinate_block: _Block) -> list[_Block]:
    return sorted(
        [
            block
            for block in blocks
            if block.page == coordinate_block.page
            and coordinate_block.y_center - 22 <= block.y_center <= coordinate_block.y_center + 22
        ],
        key=lambda block: (block.x0, block.y0),
    )


def _extract_ident(row_blocks: list[_Block], coordinate_block: _Block) -> str | None:
    left_text = _clean_text(
        " ".join(block.text for block in row_blocks if block.x0 <= coordinate_block.x0 + 10 and block.x1 >= 80)
    )
    cleaned = COORD_PAIR_RE.sub(" ", left_text)
    cleaned = ROUTE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\b\d+(?:\.\d+)?\b|[°'/]", " ", cleaned)
    candidates = [
        normalize_ident(token)
        for token in re.findall(r"\b[A-Z][A-Z0-9]{1,6}\b", cleaned.upper())
        if token not in STOPWORDS and not token.startswith("SC") and len(token) >= 3
    ]
    return candidates[-1] if candidates else None


def coord_match_is_absent(text: str) -> bool:
    return COORD_PAIR_RE.search(text) is None


def _coordinate_from_match(match: re.Match[str]) -> tuple[float, float]:
    latitude = _dms_to_decimal(
        match.group("lat_deg"),
        match.group("lat_min"),
        match.group("lat_sec"),
        match.group("lat_hemi"),
    )
    longitude = _dms_to_decimal(
        match.group("lon_deg"),
        match.group("lon_min"),
        match.group("lon_sec"),
        match.group("lon_hemi"),
    )
    return latitude, longitude


def _dms_to_decimal(degrees: str, minutes: str, seconds: str, hemisphere: str) -> float:
    decimal = int(degrees) + int(minutes) / 60 + float(seconds) / 3600
    return -decimal if hemisphere in {"S", "W"} else decimal


def _normalize_route(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}{match.group('number')}"


def _find_route(text: str) -> re.Match[str] | None:
    for match in ROUTE_RE.finditer(text):
        if match.group("prefix") in ROUTE_PREFIXES:
            return match
    return None


def _route_type(text: str) -> str | None:
    if "RNAV" in text:
        return "RNAV"
    if "CONV" in text:
        return "CONVENTIONAL"
    return None


def _drop_consecutive_duplicates(points: list[_RoutePoint]) -> list[_RoutePoint]:
    unique: list[_RoutePoint] = []
    previous_uid: str | None = None
    for point in points:
        if point.nav_point.uid == previous_uid:
            continue
        unique.append(point)
        previous_uid = point.nav_point.uid
    return unique


def _clean_text(value: str) -> str:
    return " ".join(value.replace("Ⓜ", " ").replace("\u200b", " ").split())
