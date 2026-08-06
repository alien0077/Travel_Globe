from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AirgraphPoint:
    index: int
    ident: str
    lat: float
    lon: float
    point_type: str
    source_id: str | None


@dataclass(frozen=True)
class AirwayInfo:
    index: int
    ident: str | None
    route_type: str | None
    source_id: str | None
    direction: str
    lower_limit_ft: int | None
    upper_limit_ft: int | None
    airac_cycle: str | None


@dataclass(frozen=True)
class DirectedEdge:
    from_idx: int
    to_idx: int
    airway_idx: int
    distance_nm: float
    direction: str
    min_altitude_ft: int | None
    max_altitude_ft: int | None
    source_id: str | None
    airac_cycle: str | None
    confidence: float


@dataclass(frozen=True)
class Connector:
    node_idx: int
    distance_nm: float
    heading_penalty: float
    graph_degree_penalty: float
    cost: float


DEFAULT_COST_CONFIG = {
    "connectorDistance": 1.25,
    "connectorHeading": 0.22,
    "lowGraphDegreePenalty": 14.0,
    "airwayChange": 10.0,
    "lowConfidence": 60.0,
    "turn90": 28.0,
    "turn135Reject": 135.0,
    "backtracking": 80.0,
    "deviation50": 0.0,
    "deviation150": 0.08,
    "deviationOver150": 0.22,
    "detourPenalty": 220.0,
    "maxCandidateDetour": 1.85,
    "maxRawRecoveryDetour": 1.65,
    "historicalRouteBonus": 8.0,
    "adsbSimilarityBonus": 14.0,
}


def select_ifr_route_shape(
    pack: dict[str, Any],
    origin: dict[str, Any],
    destination: dict[str, Any],
    *,
    route_id: str,
    pair_source: dict[str, Any] | None = None,
    adsb_support: dict[str, Any] | None = None,
    k: int = 10,
    cost_config: dict[str, float] | None = None,
) -> dict[str, Any]:
    config = {**DEFAULT_COST_CONFIG, **(cost_config or {})}
    graph = DirectedAirgraph(pack, config)
    return select_ifr_route_shape_from_graph(
        graph,
        origin,
        destination,
        route_id=route_id,
        pair_source=pair_source,
        adsb_support=adsb_support,
        k=k,
        config=config,
    )


def select_ifr_route_shape_from_graph(
    graph: DirectedAirgraph,
    origin: dict[str, Any],
    destination: dict[str, Any],
    *,
    route_id: str,
    pair_source: dict[str, Any] | None = None,
    adsb_support: dict[str, Any] | None = None,
    k: int = 10,
    config: dict[str, float] | None = None,
    departure: list[Connector] | None = None,
    arrival: list[Connector] | None = None,
) -> dict[str, Any]:
    config = config or graph.config
    reference = build_great_circle_reference(origin, destination)
    departure = departure if departure is not None else graph.connectors(origin, mode="departure")
    arrival = arrival if arrival is not None else graph.connectors(destination, mode="arrival")
    candidates: list[dict[str, Any]] = []
    if departure and arrival:
        for path, edge_cost, connector_pair in graph.k_shortest(origin, destination, departure, arrival, k=k):
            candidate = build_candidate(
                graph,
                origin,
                destination,
                path,
                edge_cost=edge_cost,
                connectors=connector_pair,
                pair_source=pair_source or {"exists": False},
                adsb_support=adsb_support or {},
                config=config,
            )
            if candidate["edgeValidation"]["valid"] and candidate["metrics"]["detourRatio"] <= config["maxCandidateDetour"]:
                candidates.append(candidate)
        if not candidates:
            recovery = graph.shortest_directed_path(departure, arrival)
            if recovery is not None:
                path, edge_cost, connector_pair = recovery
                candidate = build_candidate(
                    graph,
                    origin,
                    destination,
                    path,
                    edge_cost=edge_cost,
                    connectors=connector_pair,
                    pair_source=pair_source or {"exists": False},
                    adsb_support=adsb_support or {},
                    config=config,
                )
                if (
                    candidate["edgeValidation"]["valid"]
                    and candidate["metrics"]["detourRatio"] <= config["maxRawRecoveryDetour"]
                ):
                    candidate["selectionReason"] = (
                        "Distance-limited recovery path using validated directed airway segments after standard scoring "
                        "found no candidate."
                    )
                    candidate["provenance"]["recovery"] = "distance_limited_raw_directed_path"
                    candidates.append(candidate)
    candidates = dedupe_candidates(candidates)[:k]
    candidates.sort(key=lambda item: item["score"])

    if not candidates:
        return {
            "schemaVersion": 2,
            "generatedAt": datetime.now(UTC).isoformat(),
            "route": route_id,
            "routeUnavailable": True,
            "unavailableReason": unavailable_reason(departure, arrival),
            "greatCircleReference": reference,
            "connectorDiagnostics": {
                "departureConnectorCount": len(departure),
                "arrivalConnectorCount": len(arrival),
            },
            "candidates": [],
        }

    selected = candidates[0]
    return {
        "schemaVersion": 2,
        "generatedAt": datetime.now(UTC).isoformat(),
        "route": route_id,
        "routeUnavailable": False,
        "selected": {
            "method": "directed_airway_graph",
            "score": selected["score"],
            "reason": selected["selectionReason"],
            "provenance": selected["provenance"],
            "points": selected["points"],
            "airways": selected["airways"],
            "metrics": selected["metrics"],
            "edgeValidation": selected["edgeValidation"],
            "scoreBreakdown": selected["scoreBreakdown"],
        },
        "greatCircleReference": reference,
        "connectorDiagnostics": {
            "departureConnectorCount": len(departure),
            "arrivalConnectorCount": len(arrival),
        },
        "candidates": candidates,
    }


class DirectedAirgraph:
    def __init__(self, pack: dict[str, Any], config: dict[str, float]) -> None:
        self.pack = pack
        self.config = config
        self.points = [parse_point(index, row) for index, row in enumerate(pack.get("points") or [])]
        self.airways = [parse_airway(index, row) for index, row in enumerate(pack.get("airways") or [])]
        self.graph: list[list[DirectedEdge]] = [[] for _ in self.points]
        self.incoming: list[list[DirectedEdge]] = [[] for _ in self.points]
        self.edge_lookup: dict[tuple[int, int], list[DirectedEdge]] = {}
        for row in pack.get("segments") or []:
            for edge in directed_edges_from_segment(row):
                if edge.from_idx >= len(self.points) or edge.to_idx >= len(self.points):
                    continue
                self.graph[edge.from_idx].append(edge)
                self.incoming[edge.to_idx].append(edge)
                self.edge_lookup.setdefault((edge.from_idx, edge.to_idx), []).append(edge)

    def connectors(self, airport: dict[str, Any], *, mode: str) -> list[Connector]:
        assert mode in {"departure", "arrival"}
        candidates: list[Connector] = []
        for radius_nm in (80.0, 150.0):
            candidates = self._connectors_in_radius(airport, mode=mode, radius_nm=radius_nm)
            if len(candidates) >= 8:
                break
        if not candidates:
            candidates = self._connectors_in_radius(airport, mode=mode, radius_nm=450.0)[:8]
        return candidates[:30]

    def _connectors_in_radius(self, airport: dict[str, Any], *, mode: str, radius_nm: float) -> list[Connector]:
        rows: list[Connector] = []
        for point in self.points:
            edges = self.graph[point.index] if mode == "departure" else self.incoming[point.index]
            if not edges:
                continue
            distance_nm = haversine_nm(airport["latitude"], airport["longitude"], point.lat, point.lon)
            if distance_nm < 10.0 or distance_nm > radius_nm:
                continue
            heading_penalty = connector_heading_penalty(airport, point, mode=mode)
            graph_degree_penalty = 0.0 if len(edges) >= 2 else self.config["lowGraphDegreePenalty"]
            cost = (
                distance_nm * self.config["connectorDistance"]
                + heading_penalty * self.config["connectorHeading"]
                + graph_degree_penalty
            )
            rows.append(Connector(point.index, distance_nm, heading_penalty, graph_degree_penalty, cost))
        return sorted(rows, key=lambda item: item.cost)

    def k_shortest(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        departure: list[Connector],
        arrival: list[Connector],
        *,
        k: int,
    ) -> list[tuple[list[int], float, tuple[Connector, Connector]]]:
        target_nodes = {connector.node_idx: connector for connector in arrival}
        results: list[tuple[list[int], float, tuple[Connector, Connector]]] = []
        penalties: dict[tuple[int, int], float] = {}
        for iteration in range(max(k * 4, k)):
            result = self._astar(origin, destination, departure, target_nodes, penalties)
            if result is None:
                break
            path, cost, connectors = result
            if not any(edge_overlap(path, old_path) > 0.9 for old_path, _, _ in results):
                results.append(result)
                if len(results) >= k:
                    break
            penalty = 35.0 + iteration * 5.0
            for left, right in zip(path, path[1:], strict=False):
                penalties[(left, right)] = penalties.get((left, right), 0.0) + penalty
        return results

    def _astar(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        departure: list[Connector],
        arrival_by_node: dict[int, Connector],
        penalties: dict[tuple[int, int], float],
    ) -> tuple[list[int], float, tuple[Connector, Connector]] | None:
        queue: list[tuple[float, float, int, int | None, int | None]] = []
        best: dict[tuple[int, int | None, int | None], float] = {}
        previous: dict[tuple[int, int | None, int | None], tuple[int, int | None, int | None] | None] = {}
        start_connector_by_node = {connector.node_idx: connector for connector in departure}
        for connector in departure:
            state = (connector.node_idx, None, None)
            g = connector.cost
            best[state] = g
            previous[state] = None
            heapq.heappush(queue, (g + heuristic_nm(self.points[connector.node_idx], destination), g, *state))

        final_state: tuple[int, int | None, int | None] | None = None
        final_cost = math.inf
        while queue:
            _f, cost, node_idx, prev_node_idx, prev_airway_idx = heapq.heappop(queue)
            state = (node_idx, prev_node_idx, prev_airway_idx)
            if cost > best.get(state, math.inf):
                continue
            arrival = arrival_by_node.get(node_idx)
            if arrival is not None and prev_node_idx is not None:
                final_state = state
                final_cost = cost + arrival.cost
                break
            for edge in self.graph[node_idx]:
                edge_cost = self.edge_cost(edge, prev_node_idx, prev_airway_idx, origin, destination)
                if math.isinf(edge_cost):
                    continue
                next_state = (edge.to_idx, node_idx, edge.airway_idx)
                next_cost = cost + edge_cost + penalties.get((edge.from_idx, edge.to_idx), 0.0)
                if next_cost < best.get(next_state, math.inf):
                    best[next_state] = next_cost
                    previous[next_state] = state
                    heapq.heappush(
                        queue,
                        (next_cost + heuristic_nm(self.points[edge.to_idx], destination), next_cost, *next_state),
                    )
        if final_state is None:
            return None
        path: list[int] = []
        cursor: tuple[int, int | None, int | None] | None = final_state
        while cursor is not None:
            path.append(cursor[0])
            cursor = previous[cursor]
        path.reverse()
        return path, final_cost, (start_connector_by_node[path[0]], arrival_by_node[path[-1]])

    def shortest_directed_path(
        self,
        departure: list[Connector],
        arrival: list[Connector],
    ) -> tuple[list[int], float, tuple[Connector, Connector]] | None:
        if not departure or not arrival:
            return None
        arrival_by_node = {connector.node_idx: connector for connector in arrival}
        start_connector_by_node = {connector.node_idx: connector for connector in departure}
        queue: list[tuple[float, int, int]] = []
        best: dict[int, float] = {}
        previous: dict[int, int | None] = {}
        for connector in departure:
            best[connector.node_idx] = 0.0
            previous[connector.node_idx] = None
            heapq.heappush(queue, (0.0, connector.node_idx, 0))

        final_node: int | None = None
        while queue:
            cost, node_idx, depth = heapq.heappop(queue)
            if cost > best.get(node_idx, math.inf):
                continue
            if depth > 0 and node_idx in arrival_by_node:
                final_node = node_idx
                break
            for edge in self.graph[node_idx]:
                if edge.direction == "unknown":
                    continue
                next_cost = cost + edge.distance_nm
                if next_cost < best.get(edge.to_idx, math.inf):
                    best[edge.to_idx] = next_cost
                    previous[edge.to_idx] = node_idx
                    heapq.heappush(queue, (next_cost, edge.to_idx, depth + 1))

        if final_node is None:
            return None
        path: list[int] = []
        cursor: int | None = final_node
        while cursor is not None:
            path.append(cursor)
            cursor = previous[cursor]
        path.reverse()
        return path, best[final_node], (start_connector_by_node[path[0]], arrival_by_node[path[-1]])

    def edge_cost(
        self,
        edge: DirectedEdge,
        prev_node_idx: int | None,
        prev_airway_idx: int | None,
        origin: dict[str, Any],
        destination: dict[str, Any],
    ) -> float:
        if edge.direction == "unknown":
            return math.inf
        cost = edge.distance_nm
        before_destination_nm = haversine_nm(
            self.points[edge.from_idx].lat,
            self.points[edge.from_idx].lon,
            destination["latitude"],
            destination["longitude"],
        )
        after_destination_nm = haversine_nm(
            self.points[edge.to_idx].lat,
            self.points[edge.to_idx].lon,
            destination["latitude"],
            destination["longitude"],
        )
        if prev_node_idx is None and after_destination_nm > before_destination_nm + 5:
            return math.inf
        cost += (1.0 - edge.confidence) * self.config["lowConfidence"]
        if prev_airway_idx is not None and prev_airway_idx != edge.airway_idx:
            cost += self.config["airwayChange"]
        if prev_node_idx is not None:
            turn = abs_turn_degrees(
                self.points[prev_node_idx],
                self.points[edge.from_idx],
                self.points[edge.to_idx],
            )
            if turn > self.config["turn135Reject"]:
                return math.inf
            if turn > 45:
                cost += (turn - 45) / 45 * self.config["turn90"]
            if makes_backtracking(self.points[prev_node_idx], self.points[edge.from_idx], self.points[edge.to_idx], destination):
                cost += self.config["backtracking"]
        deviation = project_distance_nm(self.points[edge.to_idx].lat, self.points[edge.to_idx].lon, origin, destination)[
            "distanceNm"
        ]
        if deviation > 150:
            cost += (deviation - 150) * self.config["deviationOver150"]
        elif deviation > 50:
            cost += (deviation - 50) * self.config["deviation150"]
        return cost


def build_candidate(
    graph: DirectedAirgraph,
    origin: dict[str, Any],
    destination: dict[str, Any],
    path: list[int],
    *,
    edge_cost: float,
    connectors: tuple[Connector, Connector],
    pair_source: dict[str, Any],
    adsb_support: dict[str, Any],
    config: dict[str, float],
) -> dict[str, Any]:
    points = [airport_point(origin), *[point_payload(graph.points[index]) for index in path], airport_point(destination)]
    edges = [best_edge(graph, left, right) for left, right in zip(path, path[1:], strict=False)]
    validation = validate_route_edges(graph, path)
    direct_nm = haversine_nm(origin["latitude"], origin["longitude"], destination["latitude"], destination["longitude"])
    route_nm = route_distance_nm(points)
    detour_ratio = route_nm / direct_nm if direct_nm else math.inf
    turn_penalty = sum(turn_score(graph, path[index - 1], path[index], path[index + 1], config) for index in range(1, len(path) - 1))
    airway_changes = sum(
        1
        for index in range(1, len(edges))
        if edges[index] is not None and edges[index - 1] is not None and edges[index].airway_idx != edges[index - 1].airway_idx
    )
    deviation = great_circle_deviation_nm(points, origin, destination)
    connector_cost = connectors[0].cost + connectors[1].cost
    historical_bonus = config["historicalRouteBonus"] if pair_source.get("exists") else 0.0
    adsb_bonus = config["adsbSimilarityBonus"] if adsb_support.get("strictOriginDestinationCandidates", 0) else 0.0
    detour_penalty = max(0.0, detour_ratio - 1.18) * config["detourPenalty"]
    final_score = edge_cost + detour_penalty + turn_penalty + connector_cost - historical_bonus - adsb_bonus
    score_breakdown = {
        "distance": round(edge_cost, 2),
        "turn": round(turn_penalty, 2),
        "backtracking": 0,
        "airwayChanges": airway_changes * config["airwayChange"],
        "greatCircleDeviation": round(deviation["meanNm"], 2),
        "connector": round(connector_cost, 2),
        "historicalBonus": round(historical_bonus, 2),
        "adsbBonus": round(adsb_bonus, 2),
        "detour": round(detour_penalty, 2),
    }
    return {
        "method": "directed_airway_graph",
        "score": round(final_score, 2),
        "selectionReason": "Directed airway route with validated segment connectivity and lowest final score.",
        "provenance": {
            "source": "aviationdb-directed-airgraph",
            "originConnector": connector_payload(graph, connectors[0]),
            "destinationConnector": connector_payload(graph, connectors[1]),
            "waypointCount": len(path),
        },
        "points": points,
        "airways": [airway_payload(graph, edge) for edge in edges if edge is not None],
        "metrics": {
            "distanceNm": round(route_nm, 2),
            "directNm": round(direct_nm, 2),
            "detourRatio": round(detour_ratio, 3),
            "greatCircleMeanDeviationNm": round(deviation["meanNm"], 2),
            "greatCircleMaxDeviationNm": round(deviation["maxNm"], 2),
        },
        "edgeValidation": validation,
        "scoreBreakdown": score_breakdown,
        "nodePath": path,
    }


def validate_route_edges(graph: DirectedAirgraph, path: list[int]) -> dict[str, Any]:
    invalid = []
    for index, (left, right) in enumerate(zip(path, path[1:], strict=False)):
        edges = graph.edge_lookup.get((left, right), [])
        edge = edges[0] if edges else None
        if edge is None:
            invalid.append({"index": index, "from": left, "to": right, "reason": "missing_directed_edge"})
            continue
        if edge.direction == "unknown":
            invalid.append({"index": index, "from": left, "to": right, "reason": "unknown_direction"})
        if edge.airway_idx >= len(graph.airways) or not graph.airways[edge.airway_idx].ident:
            invalid.append({"index": index, "from": left, "to": right, "reason": "missing_airway_ident"})
    return {"valid": not invalid, "invalidSegments": invalid}


def directed_edges_from_segment(row: list[Any]) -> list[DirectedEdge]:
    from_idx = int(row[0])
    to_idx = int(row[1])
    airway_idx = int(row[2])
    distance_nm = float(row[3] or 0)
    raw_direction = normalize_direction(str(row[4] if len(row) > 4 else "unknown"))
    min_altitude = nullable_int(row[5]) if len(row) > 5 else None
    max_altitude = nullable_int(row[6]) if len(row) > 6 else None
    source_id = str(row[7]) if len(row) > 7 and row[7] is not None else None
    airac_cycle = str(row[8]) if len(row) > 8 and row[8] is not None else None
    confidence = float(row[9]) if len(row) > 9 and row[9] is not None else (0.45 if raw_direction == "unknown" else 0.7)
    if raw_direction == "both":
        return [
            DirectedEdge(from_idx, to_idx, airway_idx, distance_nm, "both", min_altitude, max_altitude, source_id, airac_cycle, confidence),
            DirectedEdge(to_idx, from_idx, airway_idx, distance_nm, "both", min_altitude, max_altitude, source_id, airac_cycle, confidence),
        ]
    if raw_direction == "backward":
        return [DirectedEdge(to_idx, from_idx, airway_idx, distance_nm, "backward", min_altitude, max_altitude, source_id, airac_cycle, confidence)]
    if raw_direction == "forward":
        return [DirectedEdge(from_idx, to_idx, airway_idx, distance_nm, "forward", min_altitude, max_altitude, source_id, airac_cycle, confidence)]
    return [DirectedEdge(from_idx, to_idx, airway_idx, distance_nm, "unknown", min_altitude, max_altitude, source_id, airac_cycle, confidence)]


def parse_point(index: int, row: list[Any]) -> AirgraphPoint:
    return AirgraphPoint(index, str(row[0]), float(row[1]), float(row[2]), str(row[3]), str(row[4]) if len(row) > 4 else None)


def parse_airway(index: int, row: list[Any]) -> AirwayInfo:
    return AirwayInfo(
        index=index,
        ident=str(row[0]) if row and row[0] is not None else None,
        route_type=str(row[1]) if len(row) > 1 and row[1] is not None else None,
        source_id=str(row[2]) if len(row) > 2 and row[2] is not None else None,
        direction=normalize_direction(str(row[3])) if len(row) > 3 and row[3] is not None else "unknown",
        lower_limit_ft=nullable_int(row[4]) if len(row) > 4 else None,
        upper_limit_ft=nullable_int(row[5]) if len(row) > 5 else None,
        airac_cycle=str(row[6]) if len(row) > 6 and row[6] is not None else None,
    )


def normalize_direction(value: str) -> str:
    value = value.strip().lower()
    if value in {"both", "bidirectional", "b", "bi", "n"}:
        return "both"
    if value in {"forward", "forwards", "f", "oneway", "one-way"}:
        return "forward"
    if value in {"backward", "reverse", "r"}:
        return "backward"
    return "unknown"


def dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        path = candidate.get("nodePath") or []
        if any(edge_overlap(path, other.get("nodePath") or []) > 0.9 for other in unique):
            continue
        unique.append(candidate)
    return unique


def best_edge(graph: DirectedAirgraph, left: int, right: int) -> DirectedEdge | None:
    edges = graph.edge_lookup.get((left, right), [])
    if not edges:
        return None
    return max(edges, key=lambda edge: edge.confidence)


def edge_overlap(left: list[int], right: list[int]) -> float:
    if len(left) < 2 or len(right) < 2:
        return 0.0
    left_edges = set(zip(left, left[1:], strict=False))
    right_edges = set(zip(right, right[1:], strict=False))
    return len(left_edges & right_edges) / max(1, min(len(left_edges), len(right_edges)))


def connector_payload(graph: DirectedAirgraph, connector: Connector) -> dict[str, Any]:
    point = graph.points[connector.node_idx]
    return {
        **point_payload(point),
        "distanceNm": round(connector.distance_nm, 2),
        "cost": round(connector.cost, 2),
    }


def airway_payload(graph: DirectedAirgraph, edge: DirectedEdge) -> dict[str, Any]:
    airway = graph.airways[edge.airway_idx] if edge.airway_idx < len(graph.airways) else None
    return {
        "from": graph.points[edge.from_idx].ident,
        "to": graph.points[edge.to_idx].ident,
        "airway": airway.ident if airway else None,
        "direction": edge.direction,
        "distanceNm": round(edge.distance_nm, 2),
        "minAltitudeFt": edge.min_altitude_ft,
        "maxAltitudeFt": edge.max_altitude_ft,
        "source": edge.source_id or (airway.source_id if airway else None),
        "airacCycle": edge.airac_cycle or (airway.airac_cycle if airway else None),
        "confidence": edge.confidence,
    }


def build_great_circle_reference(origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, Any]:
    return {
        "method": "great_circle_reference_only",
        "points": [
            {"ident": f"GC{index:02d}", "lat": round(point["lat"], 6), "lon": round(point["lon"], 6)}
            for index, point in enumerate(interpolate_great_circle(origin, destination, steps=12))
        ],
    }


def write_route_debug_outputs(result: dict[str, Any], output_dir: Path) -> None:
    route_dir = output_dir / result["route"]
    route_dir.mkdir(parents=True, exist_ok=True)
    (route_dir / "selection.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_geojson(route_dir / "great-circle.geojson", result["greatCircleReference"]["points"])
    for index, candidate in enumerate(result.get("candidates") or [], start=1):
        write_geojson(route_dir / f"candidate-{index:02d}.geojson", candidate["points"])
    if not result.get("routeUnavailable") and result.get("selected"):
        write_geojson(route_dir / "selected.geojson", result["selected"]["points"])


def write_geojson(path: Path, points: list[dict[str, Any]]) -> None:
    coordinates = [[point["lon"], point["lat"]] for point in points]
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": path.stem},
                "geometry": {"type": "LineString", "coordinates": coordinates},
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def point_payload(point: AirgraphPoint) -> dict[str, Any]:
    return {"ident": point.ident, "lat": round(point.lat, 6), "lon": round(point.lon, 6), "pointType": point.point_type}


def airport_point(airport: dict[str, Any]) -> dict[str, Any]:
    return {
        "ident": airport.get("iataCode") or airport.get("icaoCode") or airport.get("ident"),
        "lat": airport["latitude"],
        "lon": airport["longitude"],
        "pointType": "AIRPORT",
    }


def route_distance_nm(points: list[dict[str, Any]]) -> float:
    return sum(haversine_nm(points[index - 1]["lat"], points[index - 1]["lon"], points[index]["lat"], points[index]["lon"]) for index in range(1, len(points)))


def great_circle_deviation_nm(points: list[dict[str, Any]], origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, float]:
    deviations = [project_distance_nm(point["lat"], point["lon"], origin, destination)["distanceNm"] for point in points]
    return {"meanNm": sum(deviations) / len(deviations), "maxNm": max(deviations)}


def project_distance_nm(lat: float, lon: float, origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, float]:
    mid_lat = math.radians((origin["latitude"] + destination["latitude"]) / 2)
    bx = (destination["longitude"] - origin["longitude"]) * 60.108 * math.cos(mid_lat)
    by = (destination["latitude"] - origin["latitude"]) * 59.705
    px = (lon - origin["longitude"]) * 60.108 * math.cos(mid_lat)
    py = (lat - origin["latitude"]) * 59.705
    denom = bx * bx + by * by
    t = 0.0 if denom == 0 else (px * bx + py * by) / denom
    return {"t": t, "distanceNm": math.hypot(px - t * bx, py - t * by)}


def connector_heading_penalty(airport: dict[str, Any], point: AirgraphPoint, *, mode: str) -> float:
    airport_to_point = bearing_degrees(airport["latitude"], airport["longitude"], point.lat, point.lon)
    point_to_airport = bearing_degrees(point.lat, point.lon, airport["latitude"], airport["longitude"])
    heading = airport_to_point if mode == "departure" else point_to_airport
    return min(abs(heading - airport_to_point), 360 - abs(heading - airport_to_point))


def turn_score(graph: DirectedAirgraph, left: int, middle: int, right: int, config: dict[str, float]) -> float:
    turn = abs_turn_degrees(graph.points[left], graph.points[middle], graph.points[right])
    return 0.0 if turn <= 45 else (turn - 45) / 45 * config["turn90"]


def abs_turn_degrees(left: AirgraphPoint, middle: AirgraphPoint, right: AirgraphPoint) -> float:
    inbound = bearing_degrees(left.lat, left.lon, middle.lat, middle.lon)
    outbound = bearing_degrees(middle.lat, middle.lon, right.lat, right.lon)
    delta = abs(outbound - inbound)
    return min(delta, 360 - delta)


def makes_backtracking(left: AirgraphPoint, middle: AirgraphPoint, right: AirgraphPoint, destination: dict[str, Any]) -> bool:
    before = haversine_nm(middle.lat, middle.lon, destination["latitude"], destination["longitude"])
    after = haversine_nm(right.lat, right.lon, destination["latitude"], destination["longitude"])
    return after > before and abs_turn_degrees(left, middle, right) > 80


def heuristic_nm(point: AirgraphPoint, destination: dict[str, Any]) -> float:
    return haversine_nm(point.lat, point.lon, destination["latitude"], destination["longitude"])


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1 = math.radians(lat1)
    rlon1 = math.radians(lon1)
    rlat2 = math.radians(lat2)
    rlon2 = math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    value = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 3440.065 * 2 * math.asin(min(1, math.sqrt(value)))


def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(rlat2)
    x = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def interpolate_great_circle(origin: dict[str, Any], destination: dict[str, Any], steps: int) -> list[dict[str, float]]:
    lat1 = math.radians(origin["latitude"])
    lon1 = math.radians(origin["longitude"])
    lat2 = math.radians(destination["latitude"])
    lon2 = math.radians(destination["longitude"])
    delta = 2 * math.asin(
        math.sqrt(math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    )
    points = []
    for index in range(steps + 1):
        fraction = index / steps
        if delta == 0:
            lat = lat1
            lon = lon1
        else:
            a = math.sin((1 - fraction) * delta) / math.sin(delta)
            b = math.sin(fraction * delta) / math.sin(delta)
            x = a * math.cos(lat1) * math.cos(lon1) + b * math.cos(lat2) * math.cos(lon2)
            y = a * math.cos(lat1) * math.sin(lon1) + b * math.cos(lat2) * math.sin(lon2)
            z = a * math.sin(lat1) + b * math.sin(lat2)
            lat = math.atan2(z, math.sqrt(x * x + y * y))
            lon = math.atan2(y, x)
        points.append({"lat": math.degrees(lat), "lon": math.degrees(lon)})
    return points


def nullable_int(value: Any) -> int | None:
    return None if value is None or value == "" else int(value)


def unavailable_reason(departure: list[Connector], arrival: list[Connector]) -> str:
    if not departure:
        return "no_departure_connectors"
    if not arrival:
        return "no_arrival_connectors"
    return "directed_airway_path_not_found"
