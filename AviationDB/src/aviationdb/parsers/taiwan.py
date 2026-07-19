from __future__ import annotations

import re
from dataclasses import dataclass, field

from aviationdb.geo import CoordinateParseError, haversine_nm, initial_bearing_degrees, parse_coordinate_pair
from aviationdb.models import Airport, Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.html_table import extract_tables
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid, stable_uid


@dataclass
class ParsedDataset:
    airports: list[Airport] = field(default_factory=list)
    points: list[NavPoint] = field(default_factory=list)
    airways: list[Airway] = field(default_factory=list)
    segments: list[AirwaySegment] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def parse_taiwan_eaip_fixture(html: str, source_id: str) -> ParsedDataset:
    return parse_taiwan_eaip_documents({"fixture": html}, source_id)


def parse_taiwan_eaip_documents(documents: dict[str, str], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}

    for document_id, html in documents.items():
        for table in extract_tables(html):
            if not table:
                continue
            headers = [normalize_ident(header).replace(" ", "_") for header in table[0]]
            rows = table[1:]
            if "ICAO" in headers and "IATA" in headers:
                dataset.airports.extend(_parse_airports(headers, rows, source_id, dataset.issues))
            elif "IDENT" in headers and "COORDINATES" in headers:
                for point in _parse_points(headers, rows, source_id, dataset.issues):
                    point_by_ident[point.ident] = point
                    dataset.points.append(point)
            elif _is_official_enr44_table(table):
                for point in _parse_official_enr44_points(table, source_id, document_id, dataset.issues):
                    point_by_ident.setdefault(point.ident, point)
                    dataset.points.append(point)
            elif _is_official_enr34_direct_route_table(table):
                airways, segments = _parse_official_enr34_direct_routes(
                    table,
                    source_id,
                    point_by_ident,
                    dataset.points,
                    dataset.issues,
                )
                dataset.airways.extend(airways)
                dataset.segments.extend(segments)
            elif _is_official_enr35_holding_table(table):
                for point in _parse_official_enr35_holding_points(table, source_id, dataset.issues):
                    if point.ident not in point_by_ident:
                        point_by_ident[point.ident] = point
                        dataset.points.append(point)
            elif "AIRWAY" in headers and "SEQUENCE" in headers:
                airways, segments = _parse_routes(headers, rows, source_id, point_by_ident, dataset.issues)
                dataset.airways.extend(airways)
                dataset.segments.extend(segments)
        route_designator = _route_designator_from_document_id(document_id)
        if route_designator:
            airways, segments = _parse_official_route_document(
                html,
                route_designator,
                source_id,
                point_by_ident,
                dataset.points,
                dataset.issues,
            )
            dataset.airways.extend(airways)
            dataset.segments.extend(segments)

    return dataset


def _row_dict(headers: list[str], row: list[str]) -> dict[str, str]:
    return {headers[index]: row[index] if index < len(row) else "" for index in range(len(headers))}


def _parse_airports(
    headers: list[str],
    rows: list[list[str]],
    source_id: str,
    issues: list[Issue],
) -> list[Airport]:
    airports: list[Airport] = []
    for row in rows:
        item = _row_dict(headers, row)
        try:
            lat, lon = parse_coordinate_pair(item["COORDINATES"])
        except CoordinateParseError as error:
            issues.append(Issue("error", "airport-coordinate", str(error), source_id))
            continue
        icao = normalize_ident(item["ICAO"])
        airports.append(
            Airport(
                uid=stable_uid("apt", icao, source_id),
                icao=icao,
                iata=normalize_ident(item["IATA"]) or None,
                name=item["NAME"],
                latitude=lat,
                longitude=lon,
                country=item.get("COUNTRY") or "TW",
                source_id=source_id,
                fir=item.get("FIR") or "TAIPEI",
            )
        )
    return airports


def _parse_points(
    headers: list[str],
    rows: list[list[str]],
    source_id: str,
    issues: list[Issue],
) -> list[NavPoint]:
    points: list[NavPoint] = []
    for row in rows:
        item = _row_dict(headers, row)
        ident = normalize_ident(item["IDENT"])
        if not ident:
            issues.append(Issue("error", "empty-ident", "Point ident is empty", source_id))
            continue
        try:
            lat, lon = parse_coordinate_pair(item["COORDINATES"])
        except CoordinateParseError as error:
            issues.append(Issue("error", "point-coordinate", str(error), source_id, ident))
            continue
        point_type = normalize_ident(item.get("TYPE", "FIX")) or "FIX"
        points.append(
            NavPoint(
                uid=point_uid(ident, lat, lon, item.get("FIR") or "TAIPEI", point_type, source_id),
                ident=ident,
                name=item.get("NAME") or None,
                latitude=lat,
                longitude=lon,
                point_type=point_type,
                usage_type=item.get("USAGE") or None,
                country=item.get("COUNTRY") or "TW",
                fir=item.get("FIR") or "TAIPEI",
                source_id=source_id,
            )
        )
    return points


def _parse_routes(
    headers: list[str],
    rows: list[list[str]],
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    issues: list[Issue],
) -> tuple[list[Airway], list[AirwaySegment]]:
    airways_by_designator: dict[str, Airway] = {}
    route_points: dict[str, list[tuple[int, str]]] = {}
    for row in rows:
        item = _row_dict(headers, row)
        designator = normalize_ident(item["AIRWAY"])
        ident = normalize_ident(item["IDENT"])
        if not designator or not ident:
            issues.append(Issue("error", "route-row-empty", f"Invalid route row: {row}", source_id))
            continue
        sequence = int(item["SEQUENCE"])
        route_points.setdefault(designator, []).append((sequence, ident))
        airways_by_designator.setdefault(
            designator,
            Airway(
                uid=airway_uid(designator, source_id, "TAIPEI"),
                designator=designator,
                route_type=item.get("TYPE") or "RNAV",
                country=item.get("COUNTRY") or "TW",
                fir=item.get("FIR") or "TAIPEI",
                source_id=source_id,
            ),
        )

    segments: list[AirwaySegment] = []
    for designator, sequence_points in route_points.items():
        airway = airways_by_designator[designator]
        ordered = [ident for _, ident in sorted(sequence_points)]
        for index, (from_ident, to_ident) in enumerate(zip(ordered, ordered[1:], strict=False), start=1):
            from_point = point_by_ident.get(from_ident)
            to_point = point_by_ident.get(to_ident)
            if from_point is None or to_point is None:
                issues.append(
                    Issue(
                        "error",
                        "route-point-missing",
                        f"{designator} references missing point {from_ident}->{to_ident}",
                        source_id,
                        airway.uid,
                    )
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
            segments.append(
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
    return list(airways_by_designator.values()), segments


def _is_official_enr44_table(table: list[list[str]]) -> bool:
    if not table:
        return False
    header = " ".join(table[0]).upper()
    return "NAME-CODE DESIGNATOR" in header and "COORDINATES" in header


def _parse_official_enr44_points(
    table: list[list[str]],
    source_id: str,
    document_id: str,
    issues: list[Issue],
) -> list[NavPoint]:
    points: list[NavPoint] = []
    for row_number, row in enumerate(table[1:], start=2):
        if len(row) < 2 or row[0].strip().isdigit():
            continue
        ident = normalize_ident(row[0])
        coordinates = row[1].strip()
        if not ident or not coordinates:
            continue
        try:
            lat, lon = parse_coordinate_pair(coordinates)
        except CoordinateParseError as error:
            issues.append(
                Issue(
                    "warning",
                    "taiwan-enr44-coordinate",
                    f"{document_id} row {row_number}: {error}",
                    source_id,
                    ident,
                )
            )
            continue
        points.append(
            NavPoint(
                uid=point_uid(ident, lat, lon, "TAIPEI", "SIGNIFICANT_POINT", source_id),
                ident=ident,
                name=ident,
                latitude=lat,
                longitude=lon,
                point_type="SIGNIFICANT_POINT",
                usage_type="ENROUTE",
                country="TW",
                fir="TAIPEI",
                region_code="asia-east",
                source_id=source_id,
            )
        )
    return points


def _route_designator_from_document_id(document_id: str) -> str | None:
    if not document_id.startswith("route_"):
        return None
    designator = normalize_ident(document_id.removeprefix("route_"))
    return designator or None


def _parse_official_route_document(
    html: str,
    designator: str,
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[Issue],
) -> tuple[list[Airway], list[AirwaySegment]]:
    route_points = _official_route_points(html, designator, source_id, point_by_ident, dataset_points, issues)
    if len(route_points) < 2:
        issues.append(Issue("warning", "taiwan-route-too-short", f"{designator} has fewer than 2 points", source_id))
        return [], []

    airway = Airway(
        uid=airway_uid(designator, source_id, "TAIPEI"),
        designator=designator,
        route_type="ENROUTE",
        country="TW",
        fir="TAIPEI",
        source_id=source_id,
    )
    segments: list[AirwaySegment] = []
    for index, (from_point, to_point) in enumerate(zip(route_points, route_points[1:], strict=False), start=1):
        distance = haversine_nm((from_point.latitude, from_point.longitude), (to_point.latitude, to_point.longitude))
        course = initial_bearing_degrees(
            (from_point.latitude, from_point.longitude),
            (to_point.latitude, to_point.longitude),
        )
        segments.append(
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
    return [airway], segments


def _official_route_points(
    html: str,
    designator: str,
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[Issue],
) -> list[NavPoint]:
    points: list[NavPoint] = []
    seen_uids: set[str] = set()
    for table in extract_tables(html):
        parsed = _route_point_from_table(table, designator, source_id, issues)
        if parsed is None:
            continue
        ident, display_name, lat, lon, point_type = parsed
        point = point_by_ident.get(ident)
        if point is None:
            point = NavPoint(
                uid=point_uid(ident, lat, lon, "TAIPEI", point_type, source_id),
                ident=ident,
                name=display_name,
                latitude=lat,
                longitude=lon,
                point_type=point_type,
                usage_type="ENROUTE",
                country="TW",
                fir="TAIPEI",
                region_code="asia-east",
                source_id=source_id,
            )
            point_by_ident[ident] = point
            dataset_points.append(point)
        if point.uid not in seen_uids:
            points.append(point)
            seen_uids.add(point.uid)
    return points


def _route_point_from_table(
    table: list[list[str]],
    designator: str,
    source_id: str,
    issues: list[Issue],
) -> tuple[str, str, float, float, str] | None:
    if len(table) != 2 or any(len(row) < 2 for row in table):
        return None
    marker = table[0][0].strip()
    raw_name = table[0][1].strip()
    coordinates = table[1][1].strip()
    if marker not in {"▲", "△"} or not raw_name or not coordinates:
        return None
    try:
        lat, lon = parse_coordinate_pair(coordinates)
    except CoordinateParseError as error:
        issues.append(Issue("warning", "taiwan-route-coordinate", f"{designator}: {error}", source_id, raw_name))
        return None
    ident = _route_point_ident(raw_name)
    if not ident:
        issues.append(Issue("warning", "taiwan-route-ident", f"{designator}: unable to identify {raw_name}", source_id))
        return None
    point_type = "NAVAID" if "VOR" in raw_name.upper() or "NDB" in raw_name.upper() else "SIGNIFICANT_POINT"
    return ident, raw_name, lat, lon, point_type


def _route_point_ident(raw_name: str) -> str:
    quoted = re.search(r"'([A-Z0-9]{2,5})'", raw_name.upper())
    if quoted:
        return normalize_ident(quoted.group(1))
    first = re.split(r"[\s(]", raw_name.strip(), maxsplit=1)[0]
    return normalize_ident(re.sub(r"[^A-Z0-9]", "", first.upper()))


def _is_official_enr34_direct_route_table(table: list[list[str]]) -> bool:
    if not table:
        return False
    header = " ".join(table[0]).upper()
    return "ROUTE DESIGNATOR" in header and "GREAT CIRCLE" in header and any(
        row and "DIRECT ROUTE" in row[0].upper() for row in table
    )


def _parse_official_enr34_direct_routes(
    table: list[list[str]],
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[Issue],
) -> tuple[list[Airway], list[AirwaySegment]]:
    airways: list[Airway] = []
    segments: list[AirwaySegment] = []
    designator = ""
    route_points: list[NavPoint] = []

    def flush() -> None:
        if len(route_points) < 2 or not designator:
            return
        airway = Airway(
            uid=airway_uid(designator, source_id, "TAIPEI"),
            designator=designator,
            route_type="DIRECT",
            country="TW",
            fir="TAIPEI",
            source_id=source_id,
        )
        airways.append(airway)
        for index, (from_point, to_point) in enumerate(zip(route_points, route_points[1:], strict=False), start=1):
            distance = haversine_nm(
                (from_point.latitude, from_point.longitude),
                (to_point.latitude, to_point.longitude),
            )
            course = initial_bearing_degrees(
                (from_point.latitude, from_point.longitude),
                (to_point.latitude, to_point.longitude),
            )
            segments.append(
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

    for row in table[1:]:
        if not row:
            continue
        first_cell = row[0].strip()
        if "DIRECT ROUTE" in first_cell.upper():
            flush()
            designator = normalize_ident(re.sub(r"[^A-Z0-9]+", "_", first_cell.upper()).strip("_"))
            route_points = []
            continue
        parsed = _point_from_name_coordinate_cell(first_cell, "SIGNIFICANT_POINT", source_id, issues)
        if parsed is None:
            continue
        point = point_by_ident.get(parsed.ident)
        if point is None:
            point = parsed
            point_by_ident[point.ident] = point
            dataset_points.append(point)
        route_points.append(point)
    flush()
    return airways, segments


def _is_official_enr35_holding_table(table: list[list[str]]) -> bool:
    if not table:
        return False
    header = " ".join(table[0]).upper()
    return "HLDG" in header and "COORDINATES" in header and "INBD" in header


def _parse_official_enr35_holding_points(
    table: list[list[str]],
    source_id: str,
    issues: list[Issue],
) -> list[NavPoint]:
    points: list[NavPoint] = []
    for row in table[1:]:
        if not row or row[0].strip().isdigit():
            continue
        point = _point_from_name_coordinate_cell(row[0], "HOLDING_FIX", source_id, issues)
        if point is not None:
            points.append(point)
    return points


def _point_from_name_coordinate_cell(
    text: str,
    point_type: str,
    source_id: str,
    issues: list[Issue],
) -> NavPoint | None:
    match = re.search(r"([0-9]{6}(?:\.[0-9]+)?N\s+[0-9]{7}(?:\.[0-9]+)?E)", text.upper())
    if not match:
        return None
    coordinates = match.group(1)
    name = text[: match.start()].replace("△", "").replace("▲", "").replace("*", "").strip()
    ident = _route_point_ident(name)
    if not ident:
        issues.append(Issue("warning", "taiwan-point-ident", f"Unable to identify point from {text}", source_id))
        return None
    try:
        lat, lon = parse_coordinate_pair(coordinates)
    except CoordinateParseError as error:
        issues.append(Issue("warning", "taiwan-point-coordinate", str(error), source_id, ident))
        return None
    return NavPoint(
        uid=point_uid(ident, lat, lon, "TAIPEI", point_type, source_id),
        ident=ident,
        name=name or ident,
        latitude=lat,
        longitude=lon,
        point_type=point_type,
        usage_type="ENROUTE" if point_type != "HOLDING_FIX" else "HOLDING",
        country="TW",
        fir="TAIPEI",
        region_code="asia-east",
        source_id=source_id,
    )
