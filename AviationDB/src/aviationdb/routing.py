from __future__ import annotations

import heapq
import sqlite3
from dataclasses import dataclass

from aviationdb.geo import haversine_nm
from aviationdb.repository import AviationRepository

REGION_COUNTRIES = {
    "asia-east": ("TW", "JP", "KR", "HK"),
    "north-america": ("US", "CA"),
    "central-america": ("BZ", "CR", "CS", "GT", "HN", "NI", "PA", "SV"),
    "asia-southeast": ("BN", "ID", "KH", "LA", "MM", "MY", "PH", "SG", "TH", "VN"),
    "south-asia": ("BD", "IN", "LK", "MV", "NP", "PK"),
    "south-america": ("AR", "BR", "CL", "CO", "EC", "PE", "UY", "VE"),
    "africa": ("ASECNA", "BW", "EG", "ET", "GH", "KE", "MA", "MU", "NG", "SC", "ZA"),
    "middle-east": ("AE", "BH", "IL", "JO", "KW", "OM", "QA", "SA", "TR"),
    "europe": (
        "AT",
        "BE",
        "CH",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GB",
        "GR",
        "HU",
        "IE",
        "IS",
        "IT",
        "LU",
        "LV",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "SE",
    ),
}


@dataclass(frozen=True)
class RouteResult:
    origin: str
    destination: str
    method: str
    distance_nm: float
    waypoints: list[str]
    polyline: list[tuple[float, float]]
    warnings: list[str]


def route_between_airports(
    repository: AviationRepository,
    origin_code: str,
    destination_code: str,
    region: str = "asia-east",
    max_connector_nm: float = 450,
) -> RouteResult:
    origin = _airport(repository, origin_code)
    destination = _airport(repository, destination_code)
    if origin is None or destination is None:
        return _fallback(origin_code, destination_code, "airport_not_found")

    graph, point_rows = _graph(repository, region)
    if not point_rows:
        return _great_circle(origin, destination, "airway_graph_empty")

    routable_point_rows = {uid: row for uid, row in point_rows.items() if graph.get(uid)}
    origin_connectors = _nearest_points_by_component(origin, routable_point_rows, graph, max_connector_nm)
    destination_connectors = _nearest_points_by_component(destination, routable_point_rows, graph, max_connector_nm)
    if not origin_connectors or not destination_connectors:
        return _great_circle(origin, destination, "no_connector_points")

    start = "__origin__"
    goal = "__destination__"
    graph[start] = [(uid, distance) for uid, distance in origin_connectors]
    for uid, distance in destination_connectors:
        graph.setdefault(uid, []).append((goal, distance))

    previous: dict[str, str | None] = {start: None}
    distances: dict[str, float] = {start: 0.0}
    queue: list[tuple[float, str]] = [(0.0, start)]
    while queue:
        current_distance, current = heapq.heappop(queue)
        if current == goal:
            break
        if current_distance > distances.get(current, float("inf")):
            continue
        for neighbor, edge_distance in graph.get(current, []):
            candidate = current_distance + edge_distance
            if candidate < distances.get(neighbor, float("inf")):
                distances[neighbor] = candidate
                previous[neighbor] = current
                heapq.heappush(queue, (candidate, neighbor))

    if goal not in previous:
        return _great_circle(origin, destination, "airway_path_not_found")

    node: str | None = goal
    path: list[str] = []
    while node is not None:
        path.append(node)
        node = previous[node]
    path.reverse()
    route_point_uids = [uid for uid in path if uid not in {start, goal}]
    points = [point_rows[uid] for uid in route_point_uids]
    polyline = [(origin["latitude"], origin["longitude"])]
    polyline.extend((point["latitude"], point["longitude"]) for point in points)
    polyline.append((destination["latitude"], destination["longitude"]))
    return RouteResult(
        origin=origin_code.upper(),
        destination=destination_code.upper(),
        method="airway_graph",
        distance_nm=round(distances[goal], 2),
        waypoints=[point["ident"] for point in points],
        polyline=polyline,
        warnings=[],
    )


def _airport(repository: AviationRepository, code: str) -> sqlite3.Row | None:
    normalized = code.strip().upper()
    row = repository.connection.execute(
        "SELECT * FROM airport WHERE icao = ? OR iata = ? LIMIT 1",
        (normalized, normalized),
    ).fetchone()
    return row if isinstance(row, sqlite3.Row) else None


def _graph(
    repository: AviationRepository,
    region: str,
) -> tuple[dict[str, list[tuple[str, float]]], dict[str, sqlite3.Row]]:
    country_filter = REGION_COUNTRIES.get(region, ())
    if not country_filter:
        return {}, {}
    placeholders = ",".join("?" for _ in country_filter)
    point_rows = {
        row["uid"]: row
        for row in repository.rows(
            f"SELECT * FROM nav_point WHERE country IN ({placeholders})",
            tuple(country_filter),
        )
    }
    graph: dict[str, list[tuple[str, float]]] = {uid: [] for uid in point_rows}
    for row in repository.rows(
        """
        SELECT from_point_uid, to_point_uid, distance_nm
        FROM airway_segment
        WHERE from_point_uid IN (SELECT uid FROM nav_point)
          AND to_point_uid IN (SELECT uid FROM nav_point)
        """
    ):
        if row["from_point_uid"] in point_rows and row["to_point_uid"] in point_rows:
            distance = float(row["distance_nm"] or 1.0)
            graph[row["from_point_uid"]].append((row["to_point_uid"], distance))
            graph[row["to_point_uid"]].append((row["from_point_uid"], distance))
    return graph, point_rows


def _nearest_points(
    airport: sqlite3.Row,
    point_rows: dict[str, sqlite3.Row],
    max_nm: float,
) -> list[tuple[str, float]]:
    distances = []
    for uid, point in point_rows.items():
        distance = haversine_nm(
            (airport["latitude"], airport["longitude"]),
            (point["latitude"], point["longitude"]),
        )
        if distance <= max_nm:
            distances.append((uid, distance))
    return sorted(distances, key=lambda item: item[1])


def _nearest_points_by_component(
    airport: sqlite3.Row,
    point_rows: dict[str, sqlite3.Row],
    graph: dict[str, list[tuple[str, float]]],
    max_nm: float,
) -> list[tuple[str, float]]:
    component_by_uid = _components(graph)
    nearest_by_component: dict[int, tuple[str, float]] = {}
    for uid, distance in _nearest_points(airport, point_rows, max_nm):
        component = component_by_uid.get(uid)
        if component is None:
            continue
        if component not in nearest_by_component:
            nearest_by_component[component] = (uid, distance)
    return sorted(nearest_by_component.values(), key=lambda item: item[1])


def _components(graph: dict[str, list[tuple[str, float]]]) -> dict[str, int]:
    component_by_uid: dict[str, int] = {}
    component = 0
    for uid in graph:
        if uid in component_by_uid or not graph.get(uid):
            continue
        stack = [uid]
        while stack:
            current = stack.pop()
            if current in component_by_uid:
                continue
            component_by_uid[current] = component
            stack.extend(neighbor for neighbor, _distance in graph.get(current, []) if neighbor not in component_by_uid)
        component += 1
    return component_by_uid


def _fallback(origin: str, destination: str, reason: str) -> RouteResult:
    return RouteResult(origin.upper(), destination.upper(), "great_circle_fallback", 0.0, [], [], [reason])


def _great_circle(origin: sqlite3.Row, destination: sqlite3.Row, reason: str) -> RouteResult:
    distance = haversine_nm(
        (origin["latitude"], origin["longitude"]),
        (destination["latitude"], destination["longitude"]),
    )
    return RouteResult(
        origin["icao"] or origin["iata"],
        destination["icao"] or destination["iata"],
        "great_circle_fallback",
        round(distance, 2),
        [],
        [(origin["latitude"], origin["longitude"]), (destination["latitude"], destination["longitude"])],
        [reason],
    )
