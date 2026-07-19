"""Maldives CAA / MACL ANS AIP PDF Parser - canonical build integration."""
from __future__ import annotations

import re
from io import BytesIO

from aviationdb.geo import (
    CoordinateParseError,
    haversine_nm,
    initial_bearing_degrees,
)
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "COLOMBO_MALDIVES"
COUNTRY = "MV"
REGION = "asia-south"

# DMS format with symbols: 01°00'00"N 078°00'00"E
_DMS_COORD_RE = re.compile(
    r"(\d{1,2})[°\s]+(\d{1,2})['\u2019\u2032\s]+(\d{1,2}(?:\.\d+)?)"  # lat
    r'["\u201d\u2033\u2019\u2032\s]{0,2}([NS])'  # lat hemi
    r"\s+"
    r"(\d{1,3})[°\s]+(\d{1,2})['\u2019\u2032\s]+(\d{1,2}(?:\.\d+)?)"  # lon
    r'["\u201d\u2033\u2019\u2032\s]{0,2}([EW])',  # lon hemi
    re.IGNORECASE,
)
# Compact format: 010000N 0780000E (no symbols)
_COMPACT_COORD_RE = re.compile(
    r"(\d{6}(?:\.\d+)?)\s*([NS])\s+(\d{7}(?:\.\d+)?)\s*([EW])",
    re.IGNORECASE,
)
HEADER_WORDS = {
    "ROUTE", "DESIGNATOR", "SIGNIFICANT", "POINTS", "COORDINATES",
    "DIST", "TRACK", "MAG", "GEO", "ALT", "FL", "UPPER", "LOWER",
    "LIMITS", "MINIMUM", "REMARKS", "AIP", "AMDT", "ENR", "AIRAC",
    "ODD", "EVEN", "WGS84", "NM", "KM", "TYPE", "DIRECTION",
    "CLASSIFICATION", "LATERAL", "CRUISING", "LEVELS",
    "CONTROLLING", "UNIT", "FREQUENCY", "LOGON", "ADDRESS",
    "SATVOICE", "RCP", "RSP", "SPECIFICATION", "BDRY",
}


def parse_maldives_pdf_documents(documents: dict[str, bytes], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}

    for document_id, content in documents.items():
        text = _extract_pdf_text(content, document_id)
        if "enr_4_4" in document_id:
            _parse_enr44(text, source_id, dataset, point_by_ident)
        elif "enr_4_1" in document_id:
            _parse_enr41(text, source_id, dataset, point_by_ident)
        elif any(x in document_id for x in ["enr_3_1", "enr_3_2", "enr_3_5"]):
            _parse_route_text(text, source_id, dataset, point_by_ident)

    return dataset


def _extract_pdf_text(content: bytes, document_id: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages)
    if not text.strip():
        raise ValueError(f"{document_id} PDF did not yield extractable text")
    return text


def _parse_dms(text: str) -> list[tuple[float, float, int]]:
    """Parse DMS coordinates with symbols."""
    results: list[tuple[float, float, int]] = []
    for m in _DMS_COORD_RE.finditer(text):
        try:
            lat = (int(m.group(1)) + int(m.group(2)) / 60 + float(m.group(3)) / 3600)
            lon = (int(m.group(5)) + int(m.group(6)) / 60 + float(m.group(7)) / 3600)
            if m.group(4).upper() == "S":
                lat *= -1
            if m.group(8).upper() == "W":
                lon *= -1
            results.append((lat, lon, m.start()))
        except (ValueError, IndexError):
            continue
    return results


def _parse_compact(text: str) -> list[tuple[float, float, int]]:
    """Parse compact coordinate format: 010000N 0780000E."""
    results: list[tuple[float, float, int]] = []
    for m in _COMPACT_COORD_RE.finditer(text):
        try:
            lat_str = m.group(1)
            lon_str = m.group(3)
            lat_d = int(lat_str[:2])
            lat_m = int(lat_str[2:4])
            lat_s = float(lat_str[4:])
            lon_d = int(lon_str[:3])
            lon_m = int(lon_str[3:5])
            lon_s = float(lon_str[5:])
            lat = lat_d + lat_m / 60 + lat_s / 3600
            lon = lon_d + lon_m / 60 + lon_s / 3600
            if m.group(2).upper() == "S":
                lat *= -1
            if m.group(4).upper() == "W":
                lon *= -1
            results.append((lat, lon, m.start()))
        except (ValueError, IndexError):
            continue
    return results


def _all_coords(text: str) -> list[tuple[float, float, int]]:
    return _parse_dms(text) + _parse_compact(text)


def _ident_before(text: str, pos: int, max_lookback: int = 150) -> str | None:
    before = text[max(0, pos - max_lookback) : pos].strip()
    lines = before.split("\n")
    for line in reversed(lines):
        candidates = re.findall(r"\b[A-Z][A-Z0-9]{2,7}\b", line.upper())
        for c in reversed(candidates):
            if c in {"S", "E", "W", "N", "NM", "KM", "FL", "H24", "MHz", "KHz",
                     "ACC", "COP", "RDL", "DIST", "MAG", "TMA", "FIR", "RNAV",
                     "RNP", "ATC", "VOR", "DME", "NDB", "DVOR", "VORTAC",
                     "ADS", "HF", "VHF", "UHF", "CH", "ID", "ELEV", "AMDT",
                     "MIN", "MAX", "ALT", "LAT", "LON", "BDRY", "CLASS"}:
                continue
            if re.fullmatch(r"FL\d+", c) or re.fullmatch(r"\d+", c):
                continue
            return normalize_ident(c)
    return None


def _parse_enr44(
    text: str,
    source_id: str,
    dataset: ParsedDataset,
    point_by_ident: dict[str, NavPoint],
) -> None:
    """Parse ENR 4.4 significant points (compact format)."""
    coords = _all_coords(text)
    for lat, lon, pos in coords:
        ident = _ident_before(text, pos)
        if not ident or ident in point_by_ident:
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
    """Parse ENR 4.1 radio navigation aids."""
    coords = _all_coords(text)
    for lat, lon, pos in coords:
        before = text[max(0, pos - 300) : pos]
        navaid_m = re.findall(r"\(([A-Z0-9]{2,5})\)", before.upper())
        ident = None
        for c in reversed(navaid_m):
            if c not in {"CH", "ID", "NM", "H24"}:
                ident = normalize_ident(c)
                break
        if not ident:
            ident = _ident_before(text, pos)
        if not ident or ident in point_by_ident:
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


def _parse_route_text(
    text: str,
    source_id: str,
    dataset: ParsedDataset,
    point_by_ident: dict[str, NavPoint],
) -> None:
    """Parse ENR 3.x ATS route documents."""
    route_starts = list(re.finditer(r"(?m)^\s*([A-Z]{1,2}\d{3,4}[A-Z]?)\s*(?:\([^)]*\))?\s*$", text))
    if not route_starts:
        route_starts = list(re.finditer(r"\b([A-Z]\d{3,4}[A-Z]?)\s*\(?(?:RNP|RNAV)", text))

    for idx, rm in enumerate(route_starts):
        designator = normalize_ident(rm.group(1))
        if designator.startswith(("ENR", "GEN", "AD")):
            continue

        start = rm.end()
        end = route_starts[idx + 1].start() if idx + 1 < len(route_starts) else len(text)
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
        pending_dist: float | None = None

        coords = _all_coords(section)
        for lat, lon, cpos in coords:
            ident = _ident_before(section, cpos)
            if not ident:
                continue

            # Check for distance value before this point
            before = section[max(0, cpos - 200) : cpos]
            dist_m = re.search(r"(\d+(?:\.\d+)?)\s*NM", before.upper())
            if dist_m:
                pending_dist = float(dist_m.group(1))

            stored = point_by_ident.get(ident)
            if stored is None:
                stored = NavPoint(
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
                point_by_ident[ident] = stored
                dataset.points.append(stored)

            if route_points:
                prev_pt = route_points[-1]
                seq = len(route_points)
                dist = pending_dist or haversine_nm(
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
                pending_dist = None
            route_points.append(stored)

        if len(route_points) >= 2:
            dataset.airways.append(awy)
            dataset.segments.extend(route_segments)
