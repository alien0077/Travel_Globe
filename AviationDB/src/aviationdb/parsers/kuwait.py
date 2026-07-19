"""Kuwait DGCA AIS PDF Parser - canonical build integration."""
from __future__ import annotations

import re
from io import BytesIO

from aviationdb.geo import (
    CoordinateParseError,
    haversine_nm,
    initial_bearing_degrees,
    parse_coordinate,
)
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "KUWAIT"
COUNTRY = "KW"
REGION = "middle-east"

_COORD_RE = re.compile(r"(\d{6}(?:\.\d+)?[NS])\s*(\d{7}(?:\.\d+)?[EW])", re.IGNORECASE)
HEADER_WORDS = {
    "ROUTE", "DESIGNATOR", "SIGNIFICANT", "POINTS", "COORDINATES",
    "DIST", "TRACK", "MAG", "GEO", "CRUISING", "ALT", "FL",
    "UPPER", "LOWER", "LIMITS", "MINIMUM", "REMARKS", "REFER",
    "AIP", "AMDT", "ENR", "AIRAC", "DIRECTION", "CLASSIFICATION",
    "ODD", "EVEN", "WGS84", "TOWN", "NM", "KM", "JOINING",
}


def parse_kuwait_pdf_documents(documents: dict[str, bytes], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}

    for document_id, content in documents.items():
        text = _extract_pdf_text(content, document_id)
        if "enr_4_4" in document_id or "enr_4_3" in document_id:
            _parse_enr44(text, source_id, dataset, point_by_ident)
        elif "enr_4_1" in document_id:
            _parse_enr41(text, source_id, dataset, point_by_ident)
        elif any(x in document_id for x in ["enr_3_1", "enr_3_2", "enr_3_3", "enr_3_4", "enr_3_5"]):
            _parse_enr3x(text, source_id, dataset, point_by_ident)

    return dataset


def _extract_pdf_text(content: bytes, document_id: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages)
    if not text.strip():
        raise ValueError(f"{document_id} PDF did not yield extractable text")
    return text


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


def _parse_enr44(
    text: str,
    source_id: str,
    dataset: ParsedDataset,
    point_by_ident: dict[str, NavPoint],
) -> None:
    for match in _COORD_RE.finditer(text):
        prefix = text[max(0, match.start() - 160) : match.start()]
        ident = _navaid_ident_before(prefix) or _ident_before(prefix)
        if not ident or ident in point_by_ident:
            continue
        try:
            lat_str, lon_str = match.groups()
            lat = parse_coordinate(lat_str)
            lon = parse_coordinate(lon_str)
        except CoordinateParseError:
            continue
        pt = NavPoint(
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
        point_by_ident[ident] = pt
        dataset.points.append(pt)


def _parse_enr41(
    text: str,
    source_id: str,
    dataset: ParsedDataset,
    point_by_ident: dict[str, NavPoint],
) -> None:
    for match in _COORD_RE.finditer(text):
        prefix = text[max(0, match.start() - 200) : match.start()]
        ident = _navaid_ident_before(prefix)
        if not ident:
            candidates = re.findall(r"\b[A-Z][A-Z0-9]{2,5}\b", prefix.upper())
            ident = normalize_ident(candidates[-1]) if candidates else None
        if not ident or ident in point_by_ident:
            continue
        try:
            lat_str, lon_str = match.groups()
            lat = parse_coordinate(lat_str)
            lon = parse_coordinate(lon_str)
        except CoordinateParseError:
            continue
        pt = NavPoint(
            uid=point_uid(ident, lat, lon, FIR, "NAVAID", source_id),
            ident=ident,
            name=ident,
            latitude=lat,
            longitude=lon,
            point_type="NAVAID",
            usage_type="ENROUTE",
            country=COUNTRY,
            fir=FIR,
            region_code=REGION,
            source_id=source_id,
        )
        point_by_ident[ident] = pt
        dataset.points.append(pt)


def _distance_from_text(text: str) -> float | None:
    candidates = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*NM\b", text.upper())]
    candidates = [v for v in candidates if 0 < v < 800]
    return candidates[0] if candidates else None


def _parse_enr3x(
    text: str,
    source_id: str,
    dataset: ParsedDataset,
    point_by_ident: dict[str, NavPoint],
) -> None:
    designator_matches = list(re.finditer(r"(?m)^\s*([A-Z]\d{1,4}[A-Z]?)\s*$", text))
    for idx, dm in enumerate(designator_matches):
        designator = normalize_ident(dm.group(1))
        if designator.startswith(("ENR", "GEN", "AD")):
            continue
        start = dm.end()
        end = designator_matches[idx + 1].start() if idx + 1 < len(designator_matches) else len(text)
        section = text[start:end]

        awy = Airway(
            uid=airway_uid(designator, source_id, FIR),
            designator=designator,
            route_type="ATS",
            country=COUNTRY,
            fir=FIR,
            source_id=source_id,
        )
        route_points: list[NavPoint] = []
        route_segments: list[AirwaySegment] = []
        pending_distance: float | None = None

        for m in _COORD_RE.finditer(section):
            prefix = section[max(0, m.start() - 200) : m.start()]
            ident = _navaid_ident_before(prefix) or _ident_before(prefix)
            if not ident:
                continue
            try:
                lat_str, lon_str = m.groups()
                lat = parse_coordinate(lat_str)
                lon = parse_coordinate(lon_str)
            except CoordinateParseError:
                continue

            between = section[len(prefix) : m.start()] if prefix else ""
            d = pending_distance or _distance_from_text(between)

            is_navaid = bool(_navaid_ident_before(prefix))
            point_type = "NAVAID" if is_navaid else "SIGNIFICANT_POINT"

            stored = point_by_ident.get(ident)
            if stored is None:
                stored = NavPoint(
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
                point_by_ident[ident] = stored
                dataset.points.append(stored)

            if route_points:
                prev_pt = route_points[-1]
                seq = len(route_points)
                dist = d or haversine_nm(
                    (prev_pt.latitude, prev_pt.longitude), (stored.latitude, stored.longitude)
                )
                course = initial_bearing_degrees(
                    (prev_pt.latitude, prev_pt.longitude), (stored.latitude, stored.longitude)
                )
                route_segments.append(
                    AirwaySegment(
                        uid=segment_uid(awy.uid, seq, prev_pt.uid, stored.uid),
                        airway_uid=awy.uid,
                        sequence=seq,
                        from_point_uid=prev_pt.uid,
                        to_point_uid=stored.uid,
                        distance_nm=round(dist, 2),
                        initial_course_deg=round(course, 1),
                        reverse_course_deg=round((course + 180) % 360, 1),
                        source_id=source_id,
                    )
                )
            route_points.append(stored)
            pending_distance = None

        if len(route_points) >= 2:
            dataset.airways.append(awy)
            dataset.segments.extend(route_segments)
