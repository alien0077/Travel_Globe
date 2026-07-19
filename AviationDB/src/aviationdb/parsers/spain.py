from __future__ import annotations

import csv
import re
from io import StringIO

from aviationdb.geo import CoordinateParseError, haversine_nm, initial_bearing_degrees, parse_coordinate_pair
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "SPAIN"
COUNTRY = "ES"
REGION = "europe"


def parse_spain_documents(documents: dict[str, bytes], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}
    point_by_coord: dict[str, NavPoint] = {}

    for row in _csv_rows(documents, "enr_4_4_csv"):
        point = _point_from_enr44_row(row, source_id, dataset.issues)
        if point is not None:
            _store_point(point, point_by_ident, point_by_coord, dataset.points)

    for row in _csv_rows(documents, "enr_4_1_csv"):
        point = _point_from_enr41_row(row, source_id, dataset.issues)
        if point is not None:
            _store_point(point, point_by_ident, point_by_coord, dataset.points)

    airways, segments = _parse_enr32_segments(
        list(_csv_rows(documents, "enr_3_2_csv")),
        source_id,
        point_by_ident,
        point_by_coord,
        dataset.points,
        dataset.issues,
    )
    dataset.airways.extend(airways)
    dataset.segments.extend(segments)
    return dataset


def _csv_rows(documents: dict[str, bytes], document_id: str) -> list[dict[str, str]]:
    payload = documents.get(document_id)
    if payload is None:
        return []
    text = payload.decode("utf-8-sig")
    return list(csv.DictReader(StringIO(text), delimiter=";"))


def _point_from_enr44_row(row: dict[str, str], source_id: str, issues: list[Issue]) -> NavPoint | None:
    ident = row.get("Identificador_Identifier", "").strip()
    lat = row.get("Latitud_Latitude", "").strip()
    lon = row.get("Longitud_Longitude", "").strip()
    if not ident or not lat or not lon:
        return None
    return _nav_point_from_coordinate(ident, lat, lon, "SIGNIFICANT_POINT", source_id, issues)


def _point_from_enr41_row(row: dict[str, str], source_id: str, issues: list[Issue]) -> NavPoint | None:
    ident = row.get("Identificador_Identifier", "").strip()
    lat = row.get("Latitud_Latitude", "").strip()
    lon = row.get("Longitud_Longitude", "").strip()
    if not ident or not lat or not lon:
        return None
    point = _nav_point_from_coordinate(ident, lat, lon, "NAVAID", source_id, issues)
    if point is None:
        return None
    return NavPoint(
        **{
            **point.__dict__,
            "name": row.get("Nombre_Name") or None,
            "frequency": _float_value(row.get("Frecuencia_Frequency", "")),
            "channel": row.get("Canal_Channel") or None,
        }
    )


def _parse_enr32_segments(
    rows: list[dict[str, str]],
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    point_by_coord: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[Issue],
) -> tuple[list[Airway], list[AirwaySegment]]:
    airway_by_designator: dict[str, Airway] = {}
    segments: list[AirwaySegment] = []
    sequence_by_designator: dict[str, int] = {}

    for row in rows:
        designator = normalize_ident(row.get("DESIGNATOR_TXT", ""))
        if not designator:
            continue
        airway = airway_by_designator.setdefault(
            designator,
            Airway(
                uid=airway_uid(designator, source_id, FIR),
                designator=designator,
                route_type=_route_type(row),
                country=COUNTRY,
                fir=FIR,
                source_id=source_id,
            ),
        )
        from_point = _route_point(row, "INICIO", source_id, point_by_ident, point_by_coord, dataset_points, issues)
        to_point = _route_point(row, "FINAL", source_id, point_by_ident, point_by_coord, dataset_points, issues)
        if from_point is None or to_point is None:
            issues.append(
                Issue("warning", "spain-route-point-missing", f"{designator}: missing segment endpoint", source_id)
            )
            continue
        if from_point.uid == to_point.uid:
            continue
        sequence_by_designator[designator] = sequence_by_designator.get(designator, 0) + 1
        sequence = sequence_by_designator[designator]
        distance = _float_value(row.get("LENGTH_VAL", "")) or haversine_nm(
            (from_point.latitude, from_point.longitude),
            (to_point.latitude, to_point.longitude),
        )
        course = _float_value(row.get("MAGTRACK_VAL", "")) or initial_bearing_degrees(
            (from_point.latitude, from_point.longitude),
            (to_point.latitude, to_point.longitude),
        )
        reverse_course = _float_value(row.get("REVERSEMAGTRACK_VAL", "")) or (course + 180) % 360
        segments.append(
            AirwaySegment(
                uid=segment_uid(airway.uid, sequence, from_point.uid, to_point.uid),
                airway_uid=airway.uid,
                sequence=sequence,
                from_point_uid=from_point.uid,
                to_point_uid=to_point.uid,
                distance_nm=round(distance, 2),
                initial_course_deg=round(course, 1),
                reverse_course_deg=round(reverse_course, 1),
                direction=_direction(row),
                minimum_altitude_ft=_flight_level_ft(
                    row.get("DISTVERTLOWER_VAL", ""),
                    row.get("DISTVERTLOWER_UOM", ""),
                ),
                maximum_altitude_ft=_flight_level_ft(
                    row.get("DISTVERTUPPER_VAL", ""),
                    row.get("DISTVERTUPPER_UOM", ""),
                ),
                source_id=source_id,
            )
        )

    return list(airway_by_designator.values()), segments


def _route_point(
    row: dict[str, str],
    suffix: str,
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    point_by_coord: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[Issue],
) -> NavPoint | None:
    name = row.get(f"PUNTO_{suffix}", "").strip()
    lat = row.get(f"COOR_LAT_{suffix}", "").strip()
    lon = row.get(f"COOR_LON_{suffix}", "").strip()
    if not name or not lat or not lon:
        return None
    ident = _ident_from_point_name(name)
    coord_key = _coord_key_from_text(lat, lon, issues, source_id, ident)
    if coord_key is not None and coord_key in point_by_coord:
        return point_by_coord[coord_key]
    existing = point_by_ident.get(ident)
    if existing is not None:
        return existing
    point_type = "NAVAID" if _is_navaid_name(name) else "SIGNIFICANT_POINT"
    point = _nav_point_from_coordinate(ident, lat, lon, point_type, source_id, issues)
    if point is None:
        return None
    _store_point(point, point_by_ident, point_by_coord, dataset_points)
    return point


def _nav_point_from_coordinate(
    ident: str,
    lat: str,
    lon: str,
    point_type: str,
    source_id: str,
    issues: list[Issue],
) -> NavPoint | None:
    normalized = normalize_ident(ident)
    try:
        latitude, longitude = parse_coordinate_pair(f"{lat} {lon}")
    except CoordinateParseError as error:
        issues.append(Issue("warning", "spain-coordinate", str(error), source_id, normalized))
        return None
    return NavPoint(
        uid=point_uid(normalized, latitude, longitude, FIR, point_type, source_id),
        ident=normalized,
        latitude=round(latitude, 7),
        longitude=round(longitude, 7),
        point_type=point_type,
        source_id=source_id,
        country=COUNTRY,
        fir=FIR,
        region_code=REGION,
    )


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


def _ident_from_point_name(name: str) -> str:
    matches = re.findall(r"\(([A-Z0-9]{2,5})\)", name.upper())
    if matches:
        return normalize_ident(matches[-1])
    candidates = re.findall(r"\b[A-Z][A-Z0-9]{1,6}\b", name.upper())
    return normalize_ident(candidates[-1] if candidates else name)


def _is_navaid_name(name: str) -> bool:
    normalized = name.upper()
    return any(kind in normalized for kind in ("DVOR", "DME", "NDB", "TACAN", "VOR"))


def _route_type(row: dict[str, str]) -> str | None:
    return row.get("PBNACCURACY_VAL") or row.get("NAVIGATIONPERFORMANCE") or row.get("ROUTETYPE_CODE") or None


def _direction(row: dict[str, str]) -> str | None:
    odd = row.get("DIRECTION_CODE_IMPAR_ODD", "").strip()
    even = row.get("DIRECTION_CODE_PAR_EVEN", "").strip()
    if odd and even:
        return "bidirectional"
    if odd:
        return "odd"
    if even:
        return "even"
    return None


def _float_value(value: str) -> float | None:
    normalized = value.strip().replace(",", ".")
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def _flight_level_ft(value: str, unit: str) -> int | None:
    parsed = _float_value(value)
    if parsed is None:
        return None
    if unit.strip().upper() == "FL":
        return int(parsed * 100)
    return int(parsed)


def _coord_key_from_text(
    lat: str,
    lon: str,
    issues: list[Issue],
    source_id: str,
    ident: str,
) -> str | None:
    try:
        latitude, longitude = parse_coordinate_pair(f"{lat} {lon}")
    except CoordinateParseError as error:
        issues.append(Issue("warning", "spain-coordinate", str(error), source_id, ident))
        return None
    return f"{latitude:.7f},{longitude:.7f}"


def _coord_key_from_point(point: NavPoint) -> str:
    return f"{point.latitude:.7f},{point.longitude:.7f}"
