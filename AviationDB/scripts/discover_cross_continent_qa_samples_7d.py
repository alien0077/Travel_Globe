#!/usr/bin/env python3
"""Discover deterministic cross-continent route-shape QA samples.

The daily raw-derived corridor files contain endpoint candidates inferred from
the observed ADS-B traces.  This script deliberately uses those endpoint
records, rather than the IFR route graph, to select a broader and reproducible
QA set.  The selected pairs are airport-pair evidence samples; they are not a
claim that every selected pair is a single-flight callsign trace.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CELL_DEG = 0.25
EARTH_RADIUS_KM = 6371.0088
MIN_CROSS_CONTINENT_DISTANCE_KM = 2000.0
REGION_ORDER = ("NorthAmerica", "SouthAmerica", "Europe", "Africa", "Asia", "Oceania")
REGION_BOXES: dict[str, tuple[tuple[float, float, float, float], ...]] = {
    "NorthAmerica": ((15.0, 72.0, -180.0, -50.0),),
    "SouthAmerica": ((-56.0, 15.0, -90.0, -30.0),),
    "Europe": ((35.0, 72.0, -25.0, 45.0),),
    "Africa": ((-35.0, 37.0, -20.0, 52.0),),
    "Asia": ((-10.0, 35.0, 45.0, 180.0), (35.0, 60.0, 45.0, 180.0)),
    "Oceania": ((-50.0, 0.0, 110.0, 180.0), (-50.0, 0.0, -180.0, -130.0)),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-root", type=Path, required=True)
    parser.add_argument("--airports", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-continent-pair", type=int, default=4)
    parser.add_argument("--max-samples", type=int, default=52)
    parser.add_argument("--exclude-pair", action="append", default=[], help="Explicitly demote an endpoint pair, e.g. LIM->BER, while retaining it in excludedEvidence")
    args = parser.parse_args()

    airport_index = load_airports(args.airports, args.audit)
    aggregate: dict[tuple[str, str], dict[str, Any]] = {}
    processed_dates: list[str] = []
    candidate_count = 0
    for path in sorted(args.daily_root.glob("*/raw-derived-corridor.json.gz")):
        date = path.parent.name
        processed_dates.append(date)
        payload = read_gzip(path)
        for row in payload.get("endpointCandidates", []):
            candidate_count += 1
            merge_candidate(aggregate, row, date, airport_index)

    excluded_keys = {
        tuple(part.strip().upper() for part in value.replace("→", "->").split("->", 1))
        for value in args.exclude_pair
        if "->" in value.replace("→", "->")
    }
    excluded_evidence = []
    for key in sorted(excluded_keys):
        row = aggregate.get(key)
        if row:
            excluded_evidence.append({**row, "exclusionReason": "endpoint candidate was retained as negative QA evidence because the current network path failed shape QA; it is not promoted to a positive route sample"})
    candidates = [row for key, row in aggregate.items() if row.get("continentPair") and key not in excluded_keys]
    by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        by_pair[row["continentPair"]].append(row)

    selected: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {}
    for continent_pair in sorted(by_pair):
        rows = sorted(by_pair[continent_pair], key=rank_key)
        chosen = rows[: max(0, args.per_continent_pair)]
        selected.extend(chosen)
        coverage[continent_pair] = {
            "availableCandidates": len(rows),
            "selected": len(chosen),
            "selectedPairs": [f"{r['origin']}->{r['destination']}" for r in chosen],
        }

    # Preserve a hard cap while retaining deterministic strata order.
    selected = sorted(selected, key=lambda row: (row["continentPair"], rank_key(row)))[: args.max_samples]
    for index, row in enumerate(selected, 1):
        row["sampleId"] = f"cross-continent-{index:03d}"
        row["selectionReason"] = "7-day raw-derived endpoint candidate; stratified by continent pair and ranked by independent support"

    payload = {
        "schemaVersion": 1,
        "evidenceType": "cross_continent_qa_sample_manifest_v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "method": {
            "source": "local 7-day raw-derived-corridor endpointCandidates",
            "dailyRoot": str(args.daily_root),
            "cellDegrees": CELL_DEG,
            "minimumGreatCircleDistanceKm": MIN_CROSS_CONTINENT_DISTANCE_KM,
            "ifrUsed": False,
            "airportEndpointsUsed": True,
            "endpointEvidenceInterpretation": "raw-derived endpoint candidate, not callsign-specific route proof",
            "stratification": "continent pair, then support days, support legs, callsign diversity, great-circle distance",
            "perContinentPair": args.per_continent_pair,
            "maxSamples": args.max_samples,
            "excludedPairs": [f"{origin}->{destination}" for origin, destination in sorted(excluded_keys)],
        },
        "coverage": coverage,
        "stats": {
            "processedDates": sorted(processed_dates),
            "dailyCandidateRows": candidate_count,
            "uniqueAirportPairs": len(aggregate),
            "crossContinentAirportPairs": len(candidates),
            "selectedSamples": len(selected),
            "continentPairsWithCandidates": sorted(by_pair),
        },
        "selected": selected,
        "excludedEvidence": excluded_evidence,
        "limitations": [
            "Endpoint candidates identify airport-pair evidence in the raw-derived parser; they do not prove that the displayed network path belongs to the same callsign.",
            "The subsequent shape QA checks continuity, progress, detour and cross-track bounds on the shared 0.25-degree network.",
            "Inferred relay and endpoint-only bridge usage remain explicitly reported by the shape QA and are not upgraded to observed geometry.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": "complete", "stats": payload["stats"], "coverage": coverage}, ensure_ascii=False, indent=2))
    return 0


def read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def load_airports(path: Path, audit_path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    audit = read_gzip(audit_path)
    access = {
        str(row.get("iataCode") or "").upper(): row
        for row in audit.get("airportAccess", [])
        if row.get("links")
    }
    return {
        str(row.get("iataCode") or "").upper(): row
        for row in payload.get("airports", [])
        if row.get("iataCode")
        and str(row.get("iataCode")).upper() in access
        and row.get("latitude") is not None
        and row.get("longitude") is not None
    }


def merge_candidate(
    aggregate: dict[tuple[str, str], dict[str, Any]],
    row: dict[str, Any],
    date: str,
    airports: dict[str, dict[str, Any]],
) -> None:
    origin = str(row.get("originIata") or "").upper()
    destination = str(row.get("destinationIata") or "").upper()
    if origin not in airports or destination not in airports or origin == destination:
        return
    left = airports[origin]
    right = airports[destination]
    origin_region = classify_region(float(left["latitude"]), float(left["longitude"]))
    destination_region = classify_region(float(right["latitude"]), float(right["longitude"]))
    if not origin_region or not destination_region or origin_region == destination_region:
        return
    distance_km = haversine(float(left["latitude"]), float(left["longitude"]), float(right["latitude"]), float(right["longitude"]))
    if distance_km < MIN_CROSS_CONTINENT_DISTANCE_KM:
        return
    pair = "-".join(sorted((origin_region, destination_region), key=REGION_ORDER.index))
    key = (origin, destination)
    current = aggregate.setdefault(
        key,
        {
            "origin": origin,
            "destination": destination,
            "continentPair": pair,
            "originRegion": origin_region,
            "destinationRegion": destination_region,
            "supportDays": [],
            "supportLegs": 0,
            "callsignExamples": [],
            "aircraftExamples": [],
            "greatCircleDistanceKm": round(distance_km, 1),
            "airportTypes": [left.get("type"), right.get("type")],
            "scheduledService": bool(left.get("scheduledService")) and bool(right.get("scheduledService")),
        },
    )
    if date not in current["supportDays"]:
        current["supportDays"].append(date)
    current["supportLegs"] += int(row.get("supportLegs") or 0)
    current["callsignExamples"] = merge_examples(current["callsignExamples"], row.get("callsignExamples") or [])
    current["aircraftExamples"] = merge_examples(current["aircraftExamples"], row.get("aircraftExamples") or [])


def merge_examples(existing: list[str], incoming: list[Any], limit: int = 32) -> list[str]:
    return sorted(set(str(value) for value in [*existing, *incoming] if value))[:limit]


def rank_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -len(row["supportDays"]),
        -int(row["supportLegs"]),
        -len(row["callsignExamples"]),
        -int(row["scheduledService"]),
        -float(row["greatCircleDistanceKm"]),
        row["origin"],
        row["destination"],
    )


def classify_region(lat: float, lon: float) -> str | None:
    for region in REGION_ORDER:
        for min_lat, max_lat, min_lon, max_lon in REGION_BOXES[region]:
            if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                return region
    return None


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians((lon2 - lon1 + 540.0) % 360.0 - 180.0)
    value = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(value)))


if __name__ == "__main__":
    raise SystemExit(main())
