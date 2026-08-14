#!/usr/bin/env python3
"""Assemble a global relay network from the seven-day observed corridor graph.

Observed chains remain immutable.  Larger terminal-to-terminal joins are
reported as ``relay_inferred`` only when both sides have repeated multi-date
and multi-aircraft evidence; no inferred join is promoted to observed data.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import build_global_corridor_bridges as bridge_builder


EARTH_RADIUS_KM = 6371.0088


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the provisional global corridor relay network.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--chains", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--geojson", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--max-relay-km", type=float, default=1200.0)
    parser.add_argument("--max-turn-deg", type=float, default=30.0)
    parser.add_argument("--min-shared-dates", type=int, default=2)
    parser.add_argument("--min-terminal-legs", type=int, default=3)
    parser.add_argument("--min-terminal-aircraft", type=int, default=2)
    args = parser.parse_args()

    _write_status(args.status, {"state": "running", "phase": "load"})
    chains_payload = _read_gzip(args.chains)
    chains = [item for item in chains_payload.get("chains", []) if item.get("status") == "observed"]
    if not chains:
        _write_status(args.status, {"state": "blocked", "phase": "load", "reason": "no_observed_chains"})
        return 2

    terminal_evidence = bridge_builder._load_terminal_evidence(args.db, chains)
    terminals = bridge_builder._build_terminals(chains, terminal_evidence)
    starts = bridge_builder._index_starts(terminals)
    relays = bridge_builder.find_bridge_candidates(
        terminals,
        starts,
        max_bridge_km=args.max_relay_km,
        max_turn_deg=args.max_turn_deg,
        min_shared_dates=args.min_shared_dates,
        min_terminal_legs=args.min_terminal_legs,
        min_terminal_aircraft=args.min_terminal_aircraft,
    )
    supported = [item for item in relays if item.get("status") == "corridor_bridge_inferred"]
    gaps = [item for item in relays if item.get("status") == "candidate_gap"]
    relay_components = bridge_builder.build_relay_components(chains, supported)
    cross_region = [item for item in supported if _cross_region(item)]
    cross_region_pairs = sorted({
        f"{left}:{right}"
        for item in cross_region
        for left in item.get("sourceRegions", [])
        for right in item.get("targetRegions", [])
        if left != right
    })
    summary = {
        "observedChains": len(chains),
        "observedChainEdges": sum(int(item.get("edgeCount", 0)) for item in chains),
        "relayCandidates": len(relays),
        "relayInferred": len(supported),
        "unresolvedGaps": len(gaps),
        "crossRegionRelayInferred": len(cross_region),
        "crossRegionPairs": cross_region_pairs,
        "relayComponents": len(relay_components),
        "crossRegionRelayComponents": sum(int(item.get("bridgeCrossRegion", 0)) for item in relay_components),
        "rules": {
            "maxRelayKm": args.max_relay_km,
            "maxTurnDeg": args.max_turn_deg,
            "minSharedDates": args.min_shared_dates,
            "minTerminalLegs": args.min_terminal_legs,
            "minTerminalAircraft": args.min_terminal_aircraft,
        },
        "ifrExcluded": True,
        "airportPairGeneration": False,
        "scheduleGeneration": False,
        "observedGeometryUntouched": True,
        "inferredGeometryNotObserved": True,
    }
    payload = {
        "schemaVersion": 1,
        "evidenceType": "raw_derived_global_corridor_relay_network",
        "generatedAt": datetime.now(UTC).isoformat(),
        "source": {"database": str(args.db), "chains": str(args.chains)},
        "summary": summary,
        "observedChains": chains,
        "relayInferred": supported,
        "unresolvedGaps": gaps,
        "relayComponents": relay_components,
        "limitations": [
            "relayInferred joins are continuity hypotheses, not raw middle geometry",
            "unresolved gaps are never silently filled",
            "airport endpoints and schedules are not used to create relays",
        ],
    }
    _write_gzip_atomic(args.output, payload)
    _write_gzip_atomic(args.geojson, _geojson(chains, supported))
    review = {
        "schemaVersion": 1,
        "evidenceType": "global_corridor_relay_review",
        "generatedAt": datetime.now(UTC).isoformat(),
        "policy": {
            "observedOnlyForRuntime": True,
            "relayInferredRequiresReview": True,
            "unresolvedGapsExcluded": True,
            "noStraightLineAsObserved": True,
        },
        "summary": summary,
        "crossRegionRelayInferred": cross_region,
        "unresolvedGaps": gaps,
    }
    args.review_output.parent.mkdir(parents=True, exist_ok=True)
    args.review_output.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_status(args.status, {"state": "complete", "phase": "written", "summary": summary})
    print(json.dumps({"output": str(args.output), "summary": summary}, ensure_ascii=False, indent=2))
    return 0


def _cross_region(item: dict[str, Any]) -> bool:
    return any(left != right for left in item.get("sourceRegions", []) for right in item.get("targetRegions", []))


def _read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected object: {path}")
    return value


def _write_gzip_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def _geojson(chains: list[dict[str, Any]], relays: list[dict[str, Any]]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for chain in chains:
        points = chain.get("points", [])
        if len(points) < 2:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "status": "observed",
                "chainId": chain.get("chainId"),
                "supportDaysMin": chain.get("supportDaysMin"),
                "supportDaysMax": chain.get("supportDaysMax"),
                "supportLegs": chain.get("supportLegs"),
                "regionTags": chain.get("regionTags", []),
            },
            "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in points]},
        })
    for relay in relays:
        start, end = relay.get("from"), relay.get("to")
        if not start or not end:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "status": "relay_inferred",
                "bridgeId": relay.get("bridgeId"),
                "distanceKm": relay.get("distanceKm"),
                "sharedDates": relay.get("sharedDates", []),
                "sourceRegions": relay.get("sourceRegions", []),
                "targetRegions": relay.get("targetRegions", []),
                "middleGeometry": "not_observed",
            },
            "geometry": {"type": "LineString", "coordinates": [[start["lon"], start["lat"]], [end["lon"], end["lat"]]]},
        })
    return {"type": "FeatureCollection", "features": features}


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"updatedAt": datetime.now(UTC).isoformat(), **payload}
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
