#!/usr/bin/env python3
"""Build continuous observed corridor chains from the immutable global edge graph.

This is a post-merge interpretation layer.  It never changes the raw-derived
edge graph and it never fills a long middle section with a straight line.
Exact cell-to-cell edges are joined only when they share a vertex and have a
compatible direction.  Nearby chain termini are reported separately as
``unresolved_gap`` candidates for a later, evidence-backed repair pass.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path("/private/tmp/travel-globe-corridor-7d/corridor-merge.sqlite")
DEFAULT_AIRPORT_INDEX = PROJECT.parent / "shared/offline-packs/core-global/airports-index.json"
DEFAULT_OUTPUT = PROJECT / (
    "data/releases/private/observed-routes/adsblol/corridor-7d/global/global-corridor-chains.json.gz"
)
CELL_DEG = 0.25
EARTH_RADIUS_KM = 6371.0088
REGIONS = {
    "NorthAmerica": (10, 72, -170, -50),
    "SouthAmerica": (-56, 15, -82, -34),
    "Europe": (35, 72, -10, 45),
    "Africa": (-35, 37, -20, 52),
    "Asia": (5, 78, 45, 150),
    "Australia": (-45, -10, 110, 180),
}

Cell = tuple[int, int]


@dataclass(frozen=True)
class Edge:
    key: str
    start: Cell
    end: Cell
    support_days: int
    support_legs: int
    dates: tuple[str, ...] = ()
    bearing: float = 0.0


@dataclass(frozen=True)
class Chain:
    chain_id: str
    edge_keys: tuple[str, ...]
    points: tuple[tuple[float, float], ...]
    component_id: str
    support_days_min: int
    support_days_max: int
    support_legs: int
    dates: tuple[str, ...]
    length_km: float
    region_tags: tuple[str, ...]


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[Cell, Cell] = {}

    def find(self, value: Cell) -> Cell:
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: Cell, right: Cell) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build continuous global corridor chains from the merged raw edge graph."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-support-days", type=int, default=2)
    parser.add_argument("--min-chain-edges", type=int, default=4)
    parser.add_argument("--max-turn-deg", type=float, default=50.0)
    parser.add_argument("--max-gap-km", type=float, default=500.0)
    args = parser.parse_args()

    edges, union_find = load_edges(args.db, args.min_support_days)
    chains = build_chains(edges, args.max_turn_deg, union_find)
    display_chains = [chain for chain in chains if len(chain.edge_keys) >= args.min_chain_edges]
    gap_candidates = find_gap_candidates(
        display_chains,
        union_find,
        max_gap_km=args.max_gap_km,
        max_turn_deg=args.max_turn_deg,
    )
    endpoint_links = load_endpoint_links(
        args.db,
        args.airport_index,
        min_support_days=args.min_support_days,
        min_distance_km=3000.0,
    )
    summary = build_summary(edges, union_find, chains, display_chains, gap_candidates, endpoint_links)
    payload = {
        "schemaVersion": 1,
        "evidenceType": "raw_derived_global_chain",
        "generatedAt": datetime.now(UTC).isoformat(),
        "source": {
            "database": str(args.db),
            "minSupportDays": args.min_support_days,
            "rawEdgeGraphPreserved": True,
            "endpointEvidencePreserved": True,
        },
        "method": {
            "description": (
                "Join exact observed cell edges at shared vertices with directional continuity; "
                "do not invent long middle sections."
            ),
            "cellDegrees": CELL_DEG,
            "maxTurnDeg": args.max_turn_deg,
            "minChainEdges": args.min_chain_edges,
            "maxGapKm": args.max_gap_km,
        },
        "summary": summary,
        "chains": [chain_to_json(chain) for chain in display_chains],
        "gapCandidates": gap_candidates,
        "endpointLinks": endpoint_links,
        "limitations": [
            "Observed chains are not formal airway definitions.",
            "unresolved_gap candidates are not included in observed chains.",
            "Long cross-continent links require independent raw evidence before promotion.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(args.output)
    print(json.dumps({"output": str(args.output), "summary": summary}, ensure_ascii=False, indent=2))
    return 0


def load_endpoint_links(
    db_path: Path,
    airport_index_path: Path,
    *,
    min_support_days: int,
    min_distance_km: float,
) -> list[dict[str, object]]:
    airports_payload = json.loads(airport_index_path.read_text(encoding="utf-8"))
    airports = {
        str(item.get("iataCode") or "").upper(): (float(item["latitude"]), float(item["longitude"]))
        for item in airports_payload.get("airports", [])
        if item.get("iataCode") and item.get("latitude") is not None and item.get("longitude") is not None
    }
    connection = sqlite3.connect(db_path)
    rows = connection.execute(
        """
        SELECT e.origin_iata, e.destination_iata, e.support_legs,
               COUNT(d.date) AS support_days
        FROM endpoints e
        JOIN endpoint_dates d ON d.pair_key = e.pair_key
        GROUP BY e.pair_key
        HAVING COUNT(d.date) >= ?
        """,
        (min_support_days,),
    )
    links: list[dict[str, object]] = []
    for origin, destination, legs, days in rows:
        start = airports.get(str(origin).upper())
        end = airports.get(str(destination).upper())
        if start is None or end is None:
            continue
        distance = haversine_km(start, end)
        if distance < min_distance_km:
            continue
        links.append(
            {
                "originIata": str(origin).upper(),
                "destinationIata": str(destination).upper(),
                "from": {"lat": round(start[0], 5), "lon": round(start[1], 5)},
                "to": {"lat": round(end[0], 5), "lon": round(end[1], 5)},
                "distanceKm": round(distance, 1),
                "supportDays": int(days),
                "supportLegs": int(legs),
                "status": "endpoint_evidence_only",
                "reason": "long_endpoint_pair_has_raw_support_but_middle_geometry_is_not_in_the_merged_edge_graph",
            }
        )
    connection.close()
    return sorted(
        links,
        key=lambda item: (
            -int(item["supportDays"]),
            -int(item["supportLegs"]),
            str(item["originIata"]),
            str(item["destinationIata"]),
        ),
    )


def load_edges(db_path: Path, min_support_days: int) -> tuple[list[Edge], UnionFind]:
    connection = sqlite3.connect(db_path)
    rows = connection.execute(
        """
        SELECT e.edge_key, e.from_lat, e.from_lon, e.to_lat, e.to_lon,
               e.support_legs, COUNT(d.date) AS support_days,
               GROUP_CONCAT(d.date) AS dates
        FROM edges e
        JOIN edge_dates d ON d.edge_key = e.edge_key
        GROUP BY e.edge_key
        HAVING COUNT(d.date) >= ?
        """,
        (min_support_days,),
    )
    union_find = UnionFind()
    edges: list[Edge] = []
    for key, from_lat, from_lon, to_lat, to_lon, legs, days, dates in rows:
        start = (int(from_lat), int(from_lon))
        end = (int(to_lat), int(to_lon))
        union_find.union(start, end)
        edges.append(
            Edge(
                key=str(key),
                start=start,
                end=end,
                support_days=int(days),
                support_legs=int(legs),
                dates=tuple(sorted(str(value) for value in (dates or "").split(",") if value)),
                bearing=bearing_deg(cell_center(start), cell_center(end)),
            )
        )
    connection.close()
    return edges, union_find


def build_chains(edges: Iterable[Edge], max_turn_deg: float, union_find: UnionFind | None = None) -> list[Chain]:
    edge_list = list(edges)
    outgoing: dict[Cell, list[Edge]] = defaultdict(list)
    incoming: dict[Cell, list[Edge]] = defaultdict(list)
    for edge in edge_list:
        outgoing[edge.start].append(edge)
        incoming[edge.end].append(edge)
    for values in (*outgoing.values(), *incoming.values()):
        values.sort(key=lambda item: (-item.support_days, -item.support_legs, item.key))

    by_key = {edge.key: edge for edge in edge_list}
    unused = set(by_key)
    chains: list[Chain] = []
    ordered = sorted(edge_list, key=lambda item: (-item.support_days, -item.support_legs, item.key))
    for seed in ordered:
        if seed.key not in unused:
            continue
        path = [seed]
        unused.remove(seed.key)
        _extend_forward(path, outgoing, unused, max_turn_deg)
        _extend_backward(path, incoming, unused, max_turn_deg)
        chains.append(make_chain(path, len(chains), union_find))
    return chains


def _extend_forward(path: list[Edge], outgoing: dict[Cell, list[Edge]], unused: set[str], max_turn_deg: float) -> None:
    while True:
        current = path[-1]
        candidate = choose_continuation(current, outgoing.get(current.end, []), unused, max_turn_deg)
        if candidate is None:
            return
        path.append(candidate)
        unused.remove(candidate.key)


def _extend_backward(path: list[Edge], incoming: dict[Cell, list[Edge]], unused: set[str], max_turn_deg: float) -> None:
    while True:
        current = path[0]
        candidate = choose_continuation(current, incoming.get(current.start, []), unused, max_turn_deg)
        if candidate is None:
            return
        path.insert(0, candidate)
        unused.remove(candidate.key)


def choose_continuation(
    current: Edge,
    candidates: Iterable[Edge],
    unused: set[str],
    max_turn_deg: float,
) -> Edge | None:
    compatible = [
        candidate
        for candidate in candidates
        if candidate.key in unused and turn_delta_deg(current.bearing, candidate.bearing) <= max_turn_deg
    ]
    if not compatible:
        return None
    return min(
        compatible,
        key=lambda item: (
            turn_delta_deg(current.bearing, item.bearing),
            -item.support_days,
            -item.support_legs,
            item.key,
        ),
    )


def make_chain(path: list[Edge], index: int, union_find: UnionFind | None = None) -> Chain:
    points = [cell_center(path[0].start)] + [cell_center(edge.end) for edge in path]
    dates = tuple(sorted({date for edge in path for date in edge.dates}))
    return Chain(
        chain_id=f"chain-{index:06d}",
        edge_keys=tuple(edge.key for edge in path),
        points=tuple(points),
        component_id=component_id(path[0].start, union_find),
        support_days_min=min(edge.support_days for edge in path),
        support_days_max=max(edge.support_days for edge in path),
        support_legs=sum(edge.support_legs for edge in path),
        dates=dates,
        length_km=sum(
            haversine_km(left, right) for left, right in zip(points, points[1:], strict=False)
        ),
        region_tags=tuple(sorted({region for point in points for region in regions_for_point(point)})),
    )


def find_gap_candidates(
    chains: list[Chain],
    union_find: UnionFind,
    *,
    max_gap_km: float,
    max_turn_deg: float,
) -> list[dict[str, object]]:
    starts: dict[tuple[int, int], list[tuple[Chain, float]]] = defaultdict(list)
    for chain in chains:
        if len(chain.points) < 2:
            continue
        point = chain.points[0]
        starts[spatial_key(point)].append((chain, bearing_deg(chain.points[0], chain.points[1])))

    candidates: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for chain in chains:
        if len(chain.points) < 2:
            continue
        end = chain.points[-1]
        end_heading = bearing_deg(chain.points[-2], end)
        for nearby in nearby_start_cells(spatial_key(end)):
            for target, target_heading in starts.get(nearby, []):
                if target.chain_id == chain.chain_id or (chain.chain_id, target.chain_id) in seen:
                    continue
                if chain.component_id == target.component_id:
                    continue
                distance = haversine_km(end, target.points[0])
                if distance > max_gap_km:
                    continue
                bridge_heading = bearing_deg(end, target.points[0])
                if turn_delta_deg(end_heading, bridge_heading) > max_turn_deg:
                    continue
                if turn_delta_deg(bridge_heading, target_heading) > max_turn_deg:
                    continue
                seen.add((chain.chain_id, target.chain_id))
                candidates.append(
                    {
                        "fromChain": chain.chain_id,
                        "toChain": target.chain_id,
                        "from": {"lat": end[0], "lon": end[1]},
                        "to": {"lat": target.points[0][0], "lon": target.points[0][1]},
                        "distanceKm": round(distance, 1),
                        "bearingDeg": round(bridge_heading, 1),
                        "headingDeltaFromDeg": round(turn_delta_deg(end_heading, bridge_heading), 1),
                        "headingDeltaToDeg": round(turn_delta_deg(bridge_heading, target_heading), 1),
                        "status": "unresolved_gap",
                        "reason": "nearby_directionally_compatible_chain_termini_without_raw_middle_edge",
                    }
                )
    return sorted(
        candidates,
        key=lambda item: (
            float(item["distanceKm"]),
            str(item["fromChain"]),
            str(item["toChain"]),
        ),
    )


def build_summary(
    edges: list[Edge],
    union_find: UnionFind,
    chains: list[Chain],
    display_chains: list[Chain],
    gap_candidates: list[dict[str, object]],
    endpoint_links: list[dict[str, object]],
) -> dict[str, object]:
    components = {union_find.find(edge.start) for edge in edges}
    region_components: dict[str, set[Cell]] = defaultdict(set)
    for cell in union_find.parent:
        for region in regions_for_point(cell_center(cell)):
            region_components[region].add(union_find.find(cell))
    cross_region = {}
    region_names = list(REGIONS)
    for index, left in enumerate(region_names):
        for right in region_names[index + 1 :]:
            cross_region[f"{left}:{right}"] = len(region_components[left] & region_components[right])
    endpoint_region_pairs: dict[str, int] = defaultdict(int)
    for link in endpoint_links:
        start = link["from"]
        end = link["to"]
        start_regions = regions_for_point((float(start["lat"]), float(start["lon"])))
        end_regions = regions_for_point((float(end["lat"]), float(end["lon"])))
        for left in start_regions:
            for right in end_regions:
                if left != right:
                    endpoint_region_pairs[f"{left}:{right}"] += 1
    return {
        "sourceSupportedEdges": len(edges),
        "sourceVertices": len(union_find.parent),
        "sourceWeakComponents": len(components),
        "allObservedChains": len(chains),
        "displayChains": len(display_chains),
        "displayChainEdges": sum(len(chain.edge_keys) for chain in display_chains),
        "gapCandidates": len(gap_candidates),
        "longEndpointLinks": len(endpoint_links),
        "crossRegionObservedComponentOverlap": cross_region,
        "crossRegionEndpointEvidence": dict(sorted(endpoint_region_pairs.items())),
        "noStraightLineMiddleFill": True,
    }


def chain_to_json(chain: Chain) -> dict[str, object]:
    return {
        "chainId": chain.chain_id,
        "status": "observed",
        "componentId": chain.component_id,
        "edgeKeys": list(chain.edge_keys),
        "edgeCount": len(chain.edge_keys),
        "supportDaysMin": chain.support_days_min,
        "supportDaysMax": chain.support_days_max,
        "supportLegs": chain.support_legs,
        "dates": list(chain.dates),
        "lengthKm": round(chain.length_km, 1),
        "regionTags": list(chain.region_tags),
        "points": [{"lat": round(lat, 5), "lon": round(lon, 5)} for lat, lon in chain.points],
    }


def component_id(cell: Cell, union_find: UnionFind | None = None) -> str:
    root = union_find.find(cell) if union_find is not None else cell
    return f"component-{root[0]}-{root[1]}"


def cell_center(cell: Cell) -> tuple[float, float]:
    return (cell[0] * CELL_DEG - 90 + CELL_DEG / 2, cell[1] * CELL_DEG - 180 + CELL_DEG / 2)


def spatial_key(point: tuple[float, float]) -> tuple[int, int]:
    return (math.floor(point[0] / 5), math.floor(point[1] / 5))


def nearby_start_cells(key: tuple[int, int]) -> Iterable[tuple[int, int]]:
    for lat in range(key[0] - 1, key[0] + 2):
        for lon in range(key[1] - 1, key[1] + 2):
            yield lat, lon


def regions_for_point(point: tuple[float, float]) -> tuple[str, ...]:
    lat, lon = point
    return tuple(
        name
        for name, (min_lat, max_lat, min_lon, max_lon) in REGIONS.items()
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon
    )


def bearing_deg(start: tuple[float, float], end: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, start)
    lat2, lon2 = map(math.radians, end)
    delta_lon = lon2 - lon1
    x = math.sin(delta_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def turn_delta_deg(left: float, right: float) -> float:
    return abs((right - left + 180) % 360 - 180)


def haversine_km(left: tuple[float, float], right: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, left)
    lat2, lon2 = map(math.radians, right)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(value)))


if __name__ == "__main__":
    raise SystemExit(main())
