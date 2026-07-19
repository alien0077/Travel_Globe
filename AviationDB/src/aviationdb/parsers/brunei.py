"""Brunei DCA AIP PDF Parser - canonical build integration."""
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

FIR = "KOTA_KINABALU"
COUNTRY = "BN"
REGION = "asia-southeast"

_COORD_RE = re.compile(r"(\d{6}(?:\.\d+)?[NS])\s*(\d{7}(?:\.\d+)?[EW])", re.IGNORECASE)


def parse_brunei_pdf_documents(documents: dict[str, bytes], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}

    for document_id, content in documents.items():
        text = _extract_pdf_text(content, document_id)
        if "enr_3_1" in document_id:
            _parse_enr31(text, source_id, dataset, point_by_ident)
        elif "enr_4_1" in document_id:
            _parse_enr41(text, source_id, dataset, point_by_ident)

    return dataset


def _extract_pdf_text(content: bytes, document_id: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages)
    if not text.strip():
        raise ValueError(f"{document_id} PDF did not yield extractable text")
    return text


def _parse_enr41(
    text: str,
    source_id: str,
    dataset: ParsedDataset,
    point_by_ident: dict[str, NavPoint],
) -> None:
    """Parse ENR 4.1 (radio navigation aids) for navaid points."""
    for match in _COORD_RE.finditer(text):
        before = text[: match.start()].strip().split("\n")
        id_line = before[-1] if before else ""
        navaid_m = re.search(r"\(([A-Z0-9]{2,5})\)", id_line)
        if navaid_m:
            ident = normalize_ident(navaid_m.group(1))
        else:
            tokens = id_line.strip().split()
            candidate = tokens[-1].strip("()") if tokens else ""
            if re.match(r"^[A-Z0-9]{3,6}$", candidate):
                ident = normalize_ident(candidate)
            else:
                continue

        if ident in point_by_ident:
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


def _parse_enr31(
    text: str,
    source_id: str,
    dataset: ParsedDataset,
    point_by_ident: dict[str, NavPoint],
) -> None:
    """Parse Brunei ENR 3.1 ATS routes from PDF text."""
    route_blocks = re.split(r"\n\s*(?=[A-Z]\d{1,4}\s*(?:\([^)]*\))?\s*\n)", text)

    for block in route_blocks:
        block = block.strip()
        if not block:
            continue
        designator_match = re.match(r"([A-Z]\d{1,4}[A-Z]?)\s*(?:\(([^)]*)\))?", block)
        if not designator_match:
            continue
        designator = normalize_ident(designator_match.group(1))
        route_type = normalize_ident(designator_match.group(2) or "ATS")

        route_points: list[NavPoint] = []
        for m in _COORD_RE.finditer(block):
            lat_str, lon_str = m.groups()
            try:
                lat = parse_coordinate(lat_str)
                lon = parse_coordinate(lon_str)
            except CoordinateParseError:
                continue

            before = block[: m.start()].strip().split("\n")
            id_line = before[-1] if before else ""
            ident = ""
            navaid_m = re.search(r"\(([A-Z0-9]{2,5})\)\s*$", id_line)
            if navaid_m:
                ident = normalize_ident(navaid_m.group(1))
            else:
                tokens = id_line.strip().split()
                if tokens:
                    candidate = tokens[-1].strip("()")
                    if re.match(r"^[A-Z0-9]{3,6}$", candidate):
                        ident = normalize_ident(candidate)
            if not ident:
                continue

            is_navaid = any(w in id_line.upper() for w in ["DVOR", "DME", "VOR", "NDB"])
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
            route_points.append(stored)

        if len(route_points) < 2:
            dataset.issues.append(
                Issue("warning", "bn-route-too-short", f"{designator}: only {len(route_points)} points", source_id)
            )
            continue

        awy = Airway(
            uid=airway_uid(designator, source_id, FIR),
            designator=designator,
            route_type=route_type,
            country=COUNTRY,
            fir=FIR,
            source_id=source_id,
        )
        dataset.airways.append(awy)

        for i in range(1, len(route_points)):
            prev_pt = route_points[i - 1]
            curr_pt = route_points[i]
            dist = haversine_nm((prev_pt.latitude, prev_pt.longitude), (curr_pt.latitude, curr_pt.longitude))
            course = initial_bearing_degrees(
                (prev_pt.latitude, prev_pt.longitude), (curr_pt.latitude, curr_pt.longitude)
            )
            dataset.segments.append(
                AirwaySegment(
                    uid=segment_uid(awy.uid, i, prev_pt.uid, curr_pt.uid),
                    airway_uid=awy.uid,
                    sequence=i,
                    from_point_uid=prev_pt.uid,
                    to_point_uid=curr_pt.uid,
                    distance_nm=round(dist, 2),
                    initial_course_deg=round(course, 1),
                    reverse_course_deg=round((course + 180) % 360, 1),
                    source_id=source_id,
                )
            )
