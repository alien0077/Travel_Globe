#!/usr/bin/env python3
"""Find evidence-backed local relay links between observed corridor chains.

This stage is deliberately smaller than raw processing: it reads the immutable
merged SQLite edge graph and the observed-chain artifact, then emits bridge
candidates without changing either input.  A cross-continent relay may contain
many local bridges, but no single long airport-to-airport straight line is ever
created here.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sqlite3
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from build_global_corridor_chains import bearing_deg, haversine_km, turn_delta_deg

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_JOB_DIR = Path("/private/tmp/travel-globe-corridor-7d")
DEFAULT_CHAIN_INPUT = PROJECT / (
    "data/releases/private/observed-routes/adsblol/corridor-7d/global/global-corridor-chains.json.gz"
)
DEFAULT_DB = DEFAULT_JOB_DIR / "corridor-merge.sqlite"
DEFAULT_OUTPUT = PROJECT / (
    "data/releases/private/observed-routes/adsblol/corridor-7d/global/global-corridor-bridges.json.gz"
)
DEFAULT_STATUS = DEFAULT_JOB_DIR / "bridge-status.json"
GRID_DEG = 2.0
EARTH_KM_PER_DEG = 111.195


@dataclass(frozen=True)
class Terminal:
    chain_id: str
    side: str
    component_id: str
    point: tuple[float, float]
    heading_deg: float
    dates: frozenset[str]
    support_days: int
    support_legs: int
    aircraft_examples: tuple[str, ...]
    region_tags: tuple[str, ...]
    edge_key: str


@dataclass(frozen=True)
class EdgeEvidence:
    support_legs: int
    dates: frozenset[str]
    aircraft_examples: tuple[str, ...]


class DisjointSet:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, value: str) -> None:
        self.parent.setdefault(value, value)

    def find(self, value: str) -> str:
        self.add(value)
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[value] != value:
            next_value = self.parent[value]
            self.parent[value] = root
            value = next_value
        return root

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Build evidence-backed global corridor relay bridge candidates.")
    parser.add_argument("--chains", type=Path, default=DEFAULT_CHAIN_INPUT)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--max-bridge-km", type=float, default=150.0)
    parser.add_argument("--max-turn-deg", type=float, default=15.0)
    parser.add_argument("--min-shared-dates", type=int, default=2)
    parser.add_argument("--min-terminal-legs", type=int, default=3)
    parser.add_argument("--min-terminal-aircraft", type=int, default=2)
    args = parser.parse_args()

    started = time.monotonic()
    _write_status(args.status, {"state": "running", "phase": "load", "updatedAt": _now()})
    payload = _read_json_gzip(args.chains)
    chains = [item for item in payload.get("chains", []) if item.get("status") == "observed"]
    if not chains:
        _write_status(args.status, {"state": "blocked", "phase": "load", "reason": "no_observed_chains"})
        return 2
    terminal_evidence = _load_terminal_evidence(args.db, chains)
    _write_status(
        args.status,
        {
            "state": "running",
            "phase": "index",
            "chainCount": len(chains),
            "updatedAt": _now(),
        },
    )
    terminals = _build_terminals(chains, terminal_evidence)
    starts = _index_starts(terminals)
    candidates = find_bridge_candidates(
        terminals,
        starts,
        max_bridge_km=args.max_bridge_km,
        max_turn_deg=args.max_turn_deg,
        min_shared_dates=args.min_shared_dates,
        min_terminal_legs=args.min_terminal_legs,
        min_terminal_aircraft=args.min_terminal_aircraft,
    )
    supported = [item for item in candidates if item["status"] == "corridor_bridge_inferred"]
    relay_components = build_relay_components(chains, supported)
    summary = {
        "observedChains": len(chains),
        "terminals": len(terminals),
        "bridgeCandidates": len(candidates),
        "supportedRelayBridges": len(supported),
        "candidateGaps": sum(item["status"] == "candidate_gap" for item in candidates),
        "holdoutReadyBridges": sum(item["validationStatus"] == "holdout_ready" for item in supported),
        "crossRegionBridges": sum(bool(_bridge_region_pairs(item)) for item in supported),
        "relayComponents": len(relay_components),
        "observedCrossRegionRelayComponents": sum(item["observedCrossRegion"] for item in relay_components),
        "componentsWithCrossRegionBridge": sum(item["bridgeCrossRegion"] for item in relay_components),
        "maxBridgeKm": args.max_bridge_km,
        "maxTurnDeg": args.max_turn_deg,
        "minSharedDates": args.min_shared_dates,
        "minTerminalLegs": args.min_terminal_legs,
        "minTerminalAircraft": args.min_terminal_aircraft,
        "noLongStraightLineFill": True,
    }
    output_payload = {
        "schemaVersion": 1,
        "evidenceType": "raw_derived_corridor_bridge_candidate",
        "generatedAt": _now(),
        "source": {
            "chains": str(args.chains),
            "database": str(args.db),
            "ifrExcluded": True,
            "inputsPreserved": True,
        },
        "method": {
            "description": (
                "Pair observed chain termini through local waypoint-compatible relay links; "
                "a long intercontinental route must be composed of multiple local links."
            ),
            "gridDegrees": GRID_DEG,
            "maxBridgeKm": args.max_bridge_km,
            "maxTurnDeg": args.max_turn_deg,
            "minSharedDates": args.min_shared_dates,
            "minTerminalLegs": args.min_terminal_legs,
            "minTerminalAircraft": args.min_terminal_aircraft,
        },
        "summary": summary,
        "bridges": candidates,
        "relayComponents": relay_components,
        "limitations": [
            "A corridor bridge is not a single aircraft's observed full route.",
            "Terminal aircraft values are retained examples from the adjacent edge, not a complete census.",
            "No bridge is accepted when the local gap exceeds the configured limit.",
            "Airport endpoint recovery remains a separate stage.",
        ],
    }
    _write_json_gzip_atomic(args.output, output_payload)
    _write_status(
        args.status,
        {
            "state": "complete",
            "phase": "written",
            "output": str(args.output),
            "summary": summary,
            "wallSeconds": round(time.monotonic() - started, 3),
            "updatedAt": _now(),
        },
    )
    print(json.dumps({"output": str(args.output), "summary": summary}, ensure_ascii=False, indent=2))
    return 0


def find_bridge_candidates(
    terminals: list[Terminal],
    starts: dict[tuple[int, int], list[Terminal]],
    *,
    max_bridge_km: float,
    max_turn_deg: float,
    min_shared_dates: int,
    min_terminal_legs: int,
    min_terminal_aircraft: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in terminals:
        if source.side != "end":
            continue
        for target in _nearby_starts(source.point, starts, max_bridge_km):
            if source.chain_id == target.chain_id or source.component_id == target.component_id:
                continue
            pair = (source.chain_id, target.chain_id)
            if pair in seen:
                continue
            distance = haversine_km(source.point, target.point)
            if distance > max_bridge_km:
                continue
            bridge_heading = bearing_deg(source.point, target.point)
            from_delta = turn_delta_deg(source.heading_deg, bridge_heading)
            to_delta = turn_delta_deg(bridge_heading, target.heading_deg)
            if from_delta > max_turn_deg or to_delta > max_turn_deg:
                continue
            seen.add(pair)
            shared_dates = sorted(source.dates & target.dates)
            source_aircraft = len(source.aircraft_examples)
            target_aircraft = len(target.aircraft_examples)
            evidence_ok = (
                len(shared_dates) >= min_shared_dates
                and source.support_legs >= min_terminal_legs
                and target.support_legs >= min_terminal_legs
                and source_aircraft >= min_terminal_aircraft
                and target_aircraft >= min_terminal_aircraft
            )
            candidates.append(
                {
                    "bridgeId": f"bridge-{len(candidates):07d}",
                    "fromChain": source.chain_id,
                    "toChain": target.chain_id,
                    "fromComponent": source.component_id,
                    "toComponent": target.component_id,
                    "from": {"lat": round(source.point[0], 5), "lon": round(source.point[1], 5)},
                    "to": {"lat": round(target.point[0], 5), "lon": round(target.point[1], 5)},
                    "distanceKm": round(distance, 2),
                    "bearingDeg": round(bridge_heading, 2),
                    "headingDeltaFromDeg": round(from_delta, 2),
                    "headingDeltaToDeg": round(to_delta, 2),
                    "sharedDates": shared_dates,
                    "trainingDates": shared_dates[:-1] if len(shared_dates) >= 3 else shared_dates,
                    "holdoutDates": [shared_dates[-1]] if len(shared_dates) >= 3 else [],
                    "sourceSupportLegs": source.support_legs,
                    "targetSupportLegs": target.support_legs,
                    "sourceTerminalAircraftExamples": list(source.aircraft_examples),
                    "targetTerminalAircraftExamples": list(target.aircraft_examples),
                    "sourceTerminalEdge": source.edge_key,
                    "targetTerminalEdge": target.edge_key,
                    "sourceRegions": list(source.region_tags),
                    "targetRegions": list(target.region_tags),
                    "status": "corridor_bridge_inferred" if evidence_ok else "candidate_gap",
                    "validationStatus": (
                        "holdout_ready"
                        if evidence_ok and len(shared_dates) >= 3
                        else "multiday_only"
                        if evidence_ok
                        else "holdout_not_ready"
                    ),
                    "reason": (
                        "multiday_directionally_compatible_local_relay"
                        if evidence_ok
                        else "local_geometry_compatible_but_multiday_or_terminal_evidence_insufficient"
                    ),
                }
            )
    return sorted(
        candidates,
        key=lambda item: (
            0 if item["status"] == "corridor_bridge_inferred" else 1,
            float(item["distanceKm"]),
            -len(item["sharedDates"]),
            str(item["fromChain"]),
            str(item["toChain"]),
        ),
    )


def build_relay_components(chains: list[dict[str, Any]], bridges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    disjoint = DisjointSet()
    chain_by_id = {str(item["chainId"]): item for item in chains}
    for chain in chains:
        disjoint.add(str(chain["chainId"]))
    for left, right in _same_observed_component_pairs(chains):
        disjoint.union(left, right)
    for bridge in bridges:
        disjoint.union(str(bridge["fromChain"]), str(bridge["toChain"]))

    grouped: dict[str, dict[str, Any]] = {}
    for chain_id, chain in chain_by_id.items():
        root = disjoint.find(chain_id)
        item = grouped.setdefault(
            root,
            {
                "relayComponentId": f"relay-{len(grouped):06d}",
                "chainIds": [],
                "bridgeIds": [],
                "regionTags": set(),
                "dates": set(),
                "bridgeRegionPairs": set(),
            },
        )
        item["chainIds"].append(chain_id)
        item["regionTags"].update(str(value) for value in chain.get("regionTags", []))
        item["dates"].update(str(value) for value in chain.get("dates", []))
    for bridge in bridges:
        root = disjoint.find(str(bridge["fromChain"]))
        grouped[root]["bridgeIds"].append(str(bridge["bridgeId"]))
        grouped[root]["bridgeRegionPairs"].update(_bridge_region_pairs(bridge))
    output = []
    for item in grouped.values():
        if not item["bridgeIds"]:
            continue
        output.append(
            {
                "relayComponentId": item["relayComponentId"],
                "chainCount": len(item["chainIds"]),
                "bridgeCount": len(item["bridgeIds"]),
                "sampleChainIds": sorted(item["chainIds"])[:32],
                "bridgeIds": sorted(item["bridgeIds"]),
                "regionTags": sorted(item["regionTags"]),
                "dates": sorted(item["dates"]),
                "status": "corridor_relay_candidate",
                "observedCrossRegion": len(item["regionTags"]) >= 2,
                "bridgeCrossRegion": bool(item["bridgeRegionPairs"]),
                "bridgeRegionPairs": sorted(item["bridgeRegionPairs"]),
            }
        )
    return sorted(output, key=lambda item: (not item["observedCrossRegion"], item["relayComponentId"]))


def _bridge_region_pairs(bridge: dict[str, Any]) -> set[str]:
    source = {str(value) for value in bridge.get("sourceRegions", [])}
    target = {str(value) for value in bridge.get("targetRegions", [])}
    return {f"{left}:{right}" for left in source for right in target if left != right}


def _same_observed_component_pairs(chains: list[dict[str, Any]]) -> Iterable[tuple[str, str]]:
    by_component: dict[str, list[str]] = defaultdict(list)
    for chain in chains:
        by_component[str(chain["componentId"])].append(str(chain["chainId"]))
    for values in by_component.values():
        if len(values) < 2:
            continue
        first = values[0]
        for value in values[1:]:
            yield first, value


def _build_terminals(chains: list[dict[str, Any]], evidence: dict[str, EdgeEvidence]) -> list[Terminal]:
    terminals: list[Terminal] = []
    for chain in chains:
        points = [(float(item["lat"]), float(item["lon"])) for item in chain.get("points", [])]
        if len(points) < 2:
            continue
        edge_keys = [str(value) for value in chain.get("edgeKeys", [])]
        if len(edge_keys) < 1:
            # The published chain artifact always has edgeKeys; fail closed if it does not.
            continue
        chain_id = str(chain["chainId"])
        start_evidence = evidence.get(edge_keys[0], _fallback_edge_evidence(chain))
        end_evidence = evidence.get(edge_keys[-1], _fallback_edge_evidence(chain))
        common = {
            "chain_id": chain_id,
            "component_id": str(chain["componentId"]),
            "region_tags": tuple(sorted(str(value) for value in chain.get("regionTags", []))),
        }
        terminals.append(
            Terminal(
                side="start",
                point=points[0],
                heading_deg=bearing_deg(points[0], points[1]),
                edge_key=edge_keys[0],
                dates=start_evidence.dates,
                support_days=len(start_evidence.dates),
                support_legs=start_evidence.support_legs,
                aircraft_examples=start_evidence.aircraft_examples,
                **common,
            )
        )
        terminals.append(
            Terminal(
                side="end",
                point=points[-1],
                heading_deg=bearing_deg(points[-2], points[-1]),
                edge_key=edge_keys[-1],
                dates=end_evidence.dates,
                support_days=len(end_evidence.dates),
                support_legs=end_evidence.support_legs,
                aircraft_examples=end_evidence.aircraft_examples,
                **common,
            )
        )
    return terminals


def _index_starts(terminals: list[Terminal]) -> dict[tuple[int, int], list[Terminal]]:
    indexed: dict[tuple[int, int], list[Terminal]] = defaultdict(list)
    for terminal in terminals:
        if terminal.side == "start":
            indexed[_grid_key(terminal.point)].append(terminal)
    return indexed


def _nearby_starts(
    point: tuple[float, float],
    starts: dict[tuple[int, int], list[Terminal]],
    max_km: float,
) -> Iterable[Terminal]:
    lat_index, lon_index = _grid_key(point)
    radius = max(1, math.ceil(max_km / EARTH_KM_PER_DEG / GRID_DEG) + 1)
    lon_count = math.ceil(360 / GRID_DEG)
    for lat in range(lat_index - radius, lat_index + radius + 1):
        for lon in range(lon_index - radius, lon_index + radius + 1):
            yield from starts.get((lat, lon % lon_count), ())


def _grid_key(point: tuple[float, float]) -> tuple[int, int]:
    lat, lon = point
    normalized_lon = ((lon + 180) % 360) - 180
    return math.floor((lat + 90) / GRID_DEG), math.floor((normalized_lon + 180) / GRID_DEG)


def _load_terminal_evidence(db_path: Path, chains: list[dict[str, Any]]) -> dict[str, EdgeEvidence]:
    keys = sorted(
        {
            str(edge_key)
            for chain in chains
            for edge_key in (chain.get("edgeKeys", [])[:1] + chain.get("edgeKeys", [])[-1:])
        }
    )
    if not keys:
        return {}
    result: dict[str, EdgeEvidence] = {}
    connection = sqlite3.connect(db_path)
    try:
        for offset in range(0, len(keys), 800):
            batch = keys[offset : offset + 800]
            placeholders = ",".join("?" for _ in batch)
            rows = connection.execute(
                f"SELECT edge_key, aircraft_json FROM edges WHERE edge_key IN ({placeholders})",
                batch,
            )
            for edge_key, encoded in rows:
                values = json.loads(encoded or "[]")
                result[str(edge_key)] = EdgeEvidence(
                    support_legs=0,
                    dates=frozenset(),
                    aircraft_examples=tuple(sorted({str(value) for value in values if value})),
                )
            rows = connection.execute(
                f"SELECT edge_key, support_legs FROM edges WHERE edge_key IN ({placeholders})",
                batch,
            )
            for edge_key, support_legs in rows:
                current = result.get(str(edge_key))
                if current is not None:
                    result[str(edge_key)] = EdgeEvidence(
                        support_legs=int(support_legs),
                        dates=current.dates,
                        aircraft_examples=current.aircraft_examples,
                    )
            rows = connection.execute(
                f"SELECT edge_key, date FROM edge_dates WHERE edge_key IN ({placeholders})",
                batch,
            )
            dates_by_edge: dict[str, set[str]] = defaultdict(set)
            for edge_key, date in rows:
                dates_by_edge[str(edge_key)].add(str(date))
            for edge_key, dates in dates_by_edge.items():
                current = result.get(edge_key)
                if current is not None:
                    result[edge_key] = EdgeEvidence(
                        support_legs=current.support_legs,
                        dates=frozenset(dates),
                        aircraft_examples=current.aircraft_examples,
                    )
    finally:
        connection.close()
    return result


def _fallback_edge_evidence(chain: dict[str, Any]) -> EdgeEvidence:
    return EdgeEvidence(
        support_legs=int(chain.get("supportLegs", 0)),
        dates=frozenset(str(value) for value in chain.get("dates", [])),
        aircraft_examples=(),
    )


def _read_json_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected object payload: {path}")
    return value


def _write_json_gzip_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
