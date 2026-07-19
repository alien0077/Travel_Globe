"""Cuba IACC AIP PDF Parser - canonical build integration.

Cuba ENR PDFs use compact-format coordinates (203300N 0772649W) where
lat and lon are on separate lines. Route blocks are delimited by
route designators (A301, L212, etc.)."""
from __future__ import annotations

import re
from io import BytesIO

from aviationdb.geo import haversine_nm, initial_bearing_degrees
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "HAVANA"
COUNTRY = "CU"
REGION = "central-america"

# Compact coordinates with lat/lon on separate lines:
#   203300N
#   0772649W
# or inline: 231255N 0844607W
_COORD_RE = re.compile(
    r"(\d{6}(?:\.\d+)?)\s*([NS])\s*\n\s*(\d{7}(?:\.\d+)?)\s*([EW])",
    re.IGNORECASE,
)
_INLINE_COORD_RE = re.compile(
    r"(\d{6}(?:\.\d+)?)\s*([NS])\s+(\d{7}(?:\.\d+)?)\s*([EW])",
    re.IGNORECASE,
)
# Route designator on its own line: A301, L212, etc.
_ROUTE_DESIG_RE = re.compile(r"(?m)^([A-Z]\d{3,4}[A-Z]?)\s*$")
SKIP_WORDS = {
    "AIP", "ENR", "RUTAS", "ROUTES", "NAVEGACION", "CONVENCIONALES",
    "CONVENTIONAL", "AREA", "DIRECCION", "NIVELES", "CRUCERO",
    "DESIGNADOR", "RUTA", "NOMBRE", "PUNTOS", "SIGNIFICATIVOS",
    "COORDENADAS", "TRACK", "DERROTA", "DIST", "LIMITES", "SUPERIORES",
    "INFERIORES", "MEA", "CLASIFICACION", "ESPACIO", "AEREO",
    "LATERALES", "IMPAR", "PAR", "OBSERVACIONES", "DIRECTION",
    "CRUISING", "LEVELS", "ROUTE", "DESIGNATOR", "NAME", "SIGNIFICANT",
    "POINTS", "COORDINATES", "MAG", "LENGTH", "UPPER", "LOWER", "LIMIT",
    "LIMITS", "MINIMUM", "AIRSPACE", "CLASS", "LATERAL", "ODD", "EVEN",
    "REMARKS", "MOCA", "AMDT", "AIRAC", "CUBA", "SEP", "NOV", "JAN",
    "MAR", "MAY", "JUL", "AIS", "RNAV", "FORMATION", "ANGLE", "DISTANCE",
    "ELEVATION", "ANTENNA", "TIPO", "WGS84", "S", "E", "W", "N", "NM",
    "KM", "FL", "ALT", "H24", "MHZ", "KHz",
}


def parse_cuba_pdf_documents(documents: dict[str, bytes], source_id: str) -> ParsedDataset:
    """Parse Cuba ENR 3.1/3.2 PDF route documents."""
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}

    for document_id, content in documents.items():
        if "enr_3" not in document_id:
            continue
        text = _extract_pdf_text(content, document_id)
        _parse_route_document(text, source_id, dataset, point_by_ident)

    return dataset


def _extract_pdf_text(content: bytes, document_id: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages)
    if not text.strip():
        raise ValueError(f"{document_id} PDF did not yield extractable text")
    return text


def _dms_to_decimal(digits: str, hemi: str) -> float:
    """Convert compact DMS like '203300' and 'N' to decimal degrees."""
    if len(digits.split(".")[0]) >= 7:
        d = int(digits[:3])
        m = int(digits[3:5])
        s = float(digits[5:])
    else:
        d = int(digits[:2])
        m = int(digits[2:4])
        s = float(digits[4:])
    dec = d + m / 60 + s / 3600
    if hemi.upper() in ("S", "W"):
        dec *= -1
    return dec


def _extract_coords(text: str) -> list[tuple[float, float, int]]:
    """Extract all compact-format coordinates, both cross-line and inline."""
    results: list[tuple[float, float, int]] = []
    seen: set[int] = set()

    for m in _COORD_RE.finditer(text):
        try:
            lat = _dms_to_decimal(m.group(1), m.group(2))
            lon = _dms_to_decimal(m.group(3), m.group(4))
            key = round(lat, 4), round(lon, 4)
            if key not in seen:
                seen.add(key)
                results.append((lat, lon, m.start()))
        except (ValueError, IndexError):
            continue

    for m in _INLINE_COORD_RE.finditer(text):
        try:
            lat = _dms_to_decimal(m.group(1), m.group(2))
            lon = _dms_to_decimal(m.group(3), m.group(4))
            key = round(lat, 4), round(lon, 4)
            if key not in seen:
                seen.add(key)
                results.append((lat, lon, m.start()))
        except (ValueError, IndexError):
            continue

    return results


def _find_ident_before(text: str, pos: int, lookback: int = 250) -> str | None:
    """Find a waypoint/navaid identifier before a coordinate position."""
    before = text[max(0, pos - lookback) : pos]

    # Check for parenthesized navaid code: VOR/DME 'UCU'
    paren = re.findall(r"'([A-Z0-9]{2,5})'", before)
    if paren:
        return normalize_ident(paren[-1])
    paren2 = re.findall(r"\(([A-Z0-9]{2,5})\)", before)
    for c in reversed(paren2):
        if c not in ("NM", "FL", "FIR", "BDRY", "COP"):
            return normalize_ident(c)

    # Walk lines backwards
    for line in reversed(before.split("\n")):
        line = line.strip().strip("\xa0")
        if not line:
            continue
        line = re.sub(r"^[▲∆▼\uf081]\s*", "", line).strip()
        if not line:
            continue
        word = line.split()[0].strip("'\"(),;:")
        ident = re.sub(r"[^A-Z0-9]", "", word.upper())
        if ident and len(ident) >= 3 and ident not in SKIP_WORDS:
            if not re.fullmatch(r"FL\d+|\d+", ident):
                return normalize_ident(ident)
    return None


def _parse_route_document(
    text: str,
    source_id: str,
    dataset: ParsedDataset,
    point_by_ident: dict[str, NavPoint],
) -> None:
    """Split document by route designators and parse each block."""
    desig_matches = list(_ROUTE_DESIG_RE.finditer(text))
    if not desig_matches:
        return

    # Filter valid designators
    valid: list[re.Match] = []
    for m in desig_matches:
        d = m.group(1)
        if d in SKIP_WORDS:
            continue
        ctx = text[m.end() : m.end() + 100]
        if re.search(r"[▲∆]", ctx) or re.search(r"\d{6}\s*[NS]", ctx):
            valid.append(m)

    for i, match in enumerate(valid):
        start = match.start()
        end = valid[i + 1].start() if i + 1 < len(valid) else len(text)
        block = text[start:end]

        designator = normalize_ident(match.group(1))
        coords = _extract_coords(block)

        if len(coords) < 2:
            continue

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

        for lat, lon, pos in coords:
            ident = _find_ident_before(block, pos)
            if not ident:
                continue

            before = block[max(0, pos - 200) : pos]
            dm = re.search(r"(\d+(?:\.\d+)?)\s*NM", before)
            if dm:
                pending_dist = float(dm.group(1))

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
