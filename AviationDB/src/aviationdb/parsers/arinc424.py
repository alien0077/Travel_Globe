from __future__ import annotations

import re
from collections import defaultdict

from aviationdb.geo import CoordinateParseError, haversine_nm, initial_bearing_degrees, parse_coordinate_pair
from aviationdb.models import Airport, Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid, stable_uid

ARINC_COORDINATE_RE = re.compile(r"([NS]\d{8})([EW]\d{9})")
FAA_MAX_SEGMENT_NM = 700.0
FAA_REGION = "north-america"
FAA_COUNTRY_BY_AREA = {
    "CAN": "CA",
    "LAM": None,
    "PAC": None,
    "SPA": None,
    "USA": "US",
}


def parse_faa_cifp(text: str, source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_lookup: dict[tuple[str, str], NavPoint] = {}
    point_by_ident: dict[str, NavPoint] = {}
    route_rows: dict[tuple[str, str, str], list[tuple[int, str, str]]] = defaultdict(list)
    airways: dict[tuple[str, str, str], Airway] = {}

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip("\r\n")
        if not line or line.startswith("HDR"):
            continue
        if len(line) < 132:
            dataset.issues.append(Issue("warning", "faa-cifp-short-line", f"Line {line_number}", source_id))
            continue
        try:
            record = _record_key(line)
            if record == "EA":
                point = _faa_waypoint(line, source_id)
                if point is not None:
                    _store_point(point, line[1:4], line[19:21], point_lookup, point_by_ident, dataset.points)
            elif record == "P ":
                airport = _faa_airport(line, source_id)
                if airport is not None:
                    dataset.airports.append(airport)
            elif record in {"D ", "DB"}:
                point = _faa_navaid(line, source_id)
                if point is not None:
                    _store_point(point, line[1:4], line[19:21], point_lookup, point_by_ident, dataset.points)
            elif record == "ER":
                parsed = _faa_airway_row(line)
                if parsed is None:
                    continue
                designator, sequence, point_ident, point_area, route_type, customer_area = parsed
                airway_key = (designator, route_type, customer_area)
                route_rows[airway_key].append((sequence, point_ident, point_area))
                airways.setdefault(
                    airway_key,
                    Airway(
                        uid=airway_uid(designator, source_id, f"{route_type}:{customer_area}"),
                        designator=designator,
                        route_type=route_type,
                        country=_country_from_customer_area(customer_area),
                        fir=None,
                        source_id=source_id,
                    ),
                )
        except (ValueError, CoordinateParseError) as error:
            dataset.issues.append(Issue("warning", "faa-cifp-record-parse", f"Line {line_number}: {error}", source_id))

    dataset.airways.extend(airways.values())
    for airway_key, rows in sorted(route_rows.items()):
        airway = airways[airway_key]
        ordered = sorted(rows, key=lambda row: row[0])
        route_points: list[NavPoint] = []
        for _, ident, point_area in ordered:
            point = point_lookup.get((ident, point_area)) or point_by_ident.get(ident)
            if point is None:
                dataset.issues.append(
                    Issue(
                        "warning",
                        "faa-airway-point-missing",
                        f"{airway.designator}: {ident}/{point_area}",
                        source_id,
                    )
                )
                continue
            if route_points and route_points[-1].uid == point.uid:
                continue
            route_points.append(point)
        segment_index = 1
        for from_point, to_point in zip(route_points, route_points[1:], strict=False):
            distance = haversine_nm(
                (from_point.latitude, from_point.longitude),
                (to_point.latitude, to_point.longitude),
            )
            if distance > FAA_MAX_SEGMENT_NM:
                dataset.issues.append(
                    Issue(
                        "warning",
                        "faa-airway-discontinuity",
                        f"{airway.designator}: {from_point.ident}->{to_point.ident} is {distance:.1f} NM",
                        source_id,
                    )
                )
                continue
            course = initial_bearing_degrees(
                (from_point.latitude, from_point.longitude),
                (to_point.latitude, to_point.longitude),
            )
            dataset.segments.append(
                AirwaySegment(
                    uid=segment_uid(airway.uid, segment_index, from_point.uid, to_point.uid),
                    airway_uid=airway.uid,
                    sequence=segment_index,
                    from_point_uid=from_point.uid,
                    to_point_uid=to_point.uid,
                    distance_nm=round(distance, 2),
                    initial_course_deg=round(course, 1),
                    reverse_course_deg=round((course + 180) % 360, 1),
                    source_id=source_id,
                )
            )
            segment_index += 1

    return dataset


def parse_minimal_cifp_fixture(text: str, source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}
    route_rows: dict[str, list[tuple[int, str]]] = {}
    airways: dict[str, Airway] = {}

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        record_type = parts[0].upper()
        try:
            if record_type == "APT":
                airport = _airport(parts, source_id)
                dataset.airports.append(airport)
            elif record_type in {"FIX", "NAVAID"}:
                point = _point(parts, source_id, record_type)
                dataset.points.append(point)
                point_by_ident[point.ident] = point
            elif record_type == "AIRWAY":
                designator = normalize_ident(parts[1])
                sequence = int(parts[2])
                ident = normalize_ident(parts[3])
                route_rows.setdefault(designator, []).append((sequence, ident))
                airways.setdefault(
                    designator,
                    Airway(
                        uid=airway_uid(designator, source_id, parts[5] if len(parts) > 5 else None),
                        designator=designator,
                        route_type="ENROUTE",
                        country=parts[4] if len(parts) > 4 else "US",
                        fir=parts[5] if len(parts) > 5 else None,
                        source_id=source_id,
                    ),
                )
            else:
                dataset.issues.append(
                    Issue("warning", "unknown-arinc-record", f"Line {line_number}: {record_type}", source_id)
                )
        except (IndexError, ValueError, CoordinateParseError) as error:
            dataset.issues.append(
                Issue("error", "arinc-record-parse", f"Line {line_number}: {error}", source_id)
            )

    dataset.airways.extend(airways.values())
    for designator, rows in route_rows.items():
        airway = airways[designator]
        ordered = [ident for _, ident in sorted(rows)]
        for index, (from_ident, to_ident) in enumerate(zip(ordered, ordered[1:], strict=False), start=1):
            from_point = point_by_ident.get(from_ident)
            to_point = point_by_ident.get(to_ident)
            if from_point is None or to_point is None:
                dataset.issues.append(
                    Issue("error", "airway-point-missing", f"{designator}: {from_ident}->{to_ident}", source_id)
                )
                continue
            distance = haversine_nm(
                (from_point.latitude, from_point.longitude),
                (to_point.latitude, to_point.longitude),
            )
            course = initial_bearing_degrees(
                (from_point.latitude, from_point.longitude),
                (to_point.latitude, to_point.longitude),
            )
            dataset.segments.append(
                AirwaySegment(
                    uid=segment_uid(airway.uid, index, from_point.uid, to_point.uid),
                    airway_uid=airway.uid,
                    sequence=index,
                    from_point_uid=from_point.uid,
                    to_point_uid=to_point.uid,
                    distance_nm=round(distance, 2),
                    initial_course_deg=round(course, 1),
                    reverse_course_deg=round((course + 180) % 360, 1),
                    source_id=source_id,
                )
            )
    return dataset


def _record_key(line: str) -> str:
    return line[4:6]


def _faa_waypoint(line: str, source_id: str) -> NavPoint | None:
    ident = normalize_ident(line[13:18])
    if not ident:
        return None
    coordinate = _coordinate_from_line(line)
    if coordinate is None:
        return None
    lat, lon = _parse_arinc_coordinate_pair(coordinate)
    return NavPoint(
        uid=point_uid(ident, lat, lon, None, "SIGNIFICANT_POINT", source_id),
        ident=ident,
        name=normalize_ident(line[95:123]) or ident,
        latitude=lat,
        longitude=lon,
        point_type="SIGNIFICANT_POINT",
        usage_type="ENROUTE",
        country=_country_from_customer_area(line[1:4]),
        fir=None,
        region_code=FAA_REGION,
        source_id=source_id,
    )


def _faa_airport(line: str, source_id: str) -> Airport | None:
    if line[12] != "A":
        return None
    icao = normalize_ident(line[6:10])
    if len(icao) != 4 or not icao.isalpha():
        return None
    coordinate = _coordinate_from_line(line)
    if coordinate is None:
        return None
    lat, lon = _parse_arinc_coordinate_pair(coordinate)
    iata = normalize_ident(line[13:16])
    return Airport(
        uid=stable_uid("apt", icao, source_id),
        icao=icao,
        iata=iata if len(iata) == 3 and iata.isalpha() else None,
        name=normalize_ident(line[93:123]) or icao,
        latitude=lat,
        longitude=lon,
        country=_country_from_customer_area(line[1:4]),
        source_id=source_id,
    )


def _faa_navaid(line: str, source_id: str) -> NavPoint | None:
    ident = normalize_ident(line[13:18])
    if not ident:
        return None
    coordinate = _coordinate_from_line(line)
    if coordinate is None:
        return None
    lat, lon = _parse_arinc_coordinate_pair(coordinate)
    return NavPoint(
        uid=point_uid(ident, lat, lon, None, "NAVAID", source_id),
        ident=ident,
        name=normalize_ident(line[93:123]) or ident,
        latitude=lat,
        longitude=lon,
        point_type="NAVAID",
        usage_type="ENROUTE",
        country=_country_from_customer_area(line[1:4]),
        fir=None,
        region_code=FAA_REGION,
        source_id=source_id,
    )


def _faa_airway_row(line: str) -> tuple[str, int, str, str, str, str] | None:
    designator = normalize_ident(line[13:18])
    if not designator:
        return None
    sequence_text = line[25:29].strip()
    if not sequence_text.isdigit():
        return None
    point_ident = normalize_ident(line[29:34])
    if not point_ident:
        return None
    point_area = line[34:36].strip()
    route_type = _faa_route_type(designator)
    customer_area = line[1:4].strip()
    return designator, int(sequence_text), point_ident, point_area, route_type, customer_area


def _faa_route_type(designator: str) -> str:
    if designator.startswith("J"):
        return "JET"
    if designator.startswith(("Q", "T")):
        return "RNAV"
    return "VICTOR" if designator.startswith("V") else "ENROUTE"


def _coordinate_from_line(line: str) -> tuple[str, str] | None:
    match = ARINC_COORDINATE_RE.search(line)
    if match is None:
        return None
    return match.group(1), match.group(2)


def _parse_arinc_coordinate_pair(coordinate: tuple[str, str]) -> tuple[float, float]:
    lat_raw, lon_raw = coordinate
    lat = _parse_arinc_coordinate(lat_raw)
    lon = _parse_arinc_coordinate(lon_raw)
    return lat, lon


def _parse_arinc_coordinate(value: str) -> float:
    hemisphere = value[0]
    digits = value[1:]
    degree_digits = 3 if hemisphere in {"E", "W"} else 2
    degrees = int(digits[:degree_digits])
    minutes = int(digits[degree_digits : degree_digits + 2])
    seconds = int(digits[degree_digits + 2 : degree_digits + 4])
    hundredths = int(digits[degree_digits + 4 : degree_digits + 6])
    decimal = degrees + minutes / 60 + (seconds + hundredths / 100) / 3600
    if hemisphere in {"S", "W"}:
        decimal *= -1
    return decimal


def _country_from_customer_area(area: str) -> str | None:
    return FAA_COUNTRY_BY_AREA.get(area.strip(), area.strip() or None)


def _store_point(
    point: NavPoint,
    customer_area: str,
    icao_region: str,
    point_lookup: dict[tuple[str, str], NavPoint],
    point_by_ident: dict[str, NavPoint],
    dataset_points: list[NavPoint],
) -> None:
    area = icao_region.strip()
    if point.ident in point_by_ident:
        stored_point = point_by_ident[point.ident]
        point_lookup[(point.ident, area)] = stored_point
        point_lookup[(point.ident, customer_area.strip())] = stored_point
        return
    point_by_ident[point.ident] = point
    point_lookup[(point.ident, area)] = point
    point_lookup[(point.ident, customer_area.strip())] = point
    dataset_points.append(point)


def _airport(parts: list[str], source_id: str) -> Airport:
    _, icao, iata, name, coordinates, country = parts[:6]
    lat, lon = parse_coordinate_pair(coordinates)
    return Airport(
        uid=stable_uid("apt", icao, source_id),
        icao=normalize_ident(icao),
        iata=normalize_ident(iata) or None,
        name=name,
        latitude=lat,
        longitude=lon,
        country=country,
        source_id=source_id,
    )


def _point(parts: list[str], source_id: str, record_type: str) -> NavPoint:
    _, ident, name, coordinates, country, fir = parts[:6]
    lat, lon = parse_coordinate_pair(coordinates)
    point_type = "NAVAID" if record_type == "NAVAID" else "FIX"
    return NavPoint(
        uid=point_uid(ident, lat, lon, fir, point_type, source_id),
        ident=normalize_ident(ident),
        name=name or None,
        latitude=lat,
        longitude=lon,
        point_type=point_type,
        country=country,
        fir=fir,
        source_id=source_id,
    )
