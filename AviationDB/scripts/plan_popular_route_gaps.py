#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_AIRPORT_INDEX = PROJECT / "shared" / "offline-packs" / "core-global" / "airports-index.json"
DEFAULT_CONTEXT_INDEX = PROJECT / "shared" / "offline-packs" / "core-global" / "aviation-context-index.json"
DEFAULT_OBSERVED_PACK = (
    PROJECT / "AviationDB" / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "observed-routes.global.json.gz"
)
DEFAULT_OUTPUT = (
    PROJECT / "AviationDB" / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "popular-route-gaps.json"
)


IMPORTANT_TW_ROUTES = {
    ("KHH", "NRT"),
    ("KHH", "KIX"),
    ("KHH", "HND"),
    ("KHH", "OKA"),
    ("KHH", "HKG"),
    ("KHH", "ICN"),
    ("KHH", "PUS"),
    ("KHH", "BKK"),
    ("KHH", "DMK"),
    ("KHH", "SIN"),
    ("KHH", "MNL"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan high-value observed-route gaps.")
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--context-index", type=Path, default=DEFAULT_CONTEXT_INDEX)
    parser.add_argument("--observed-pack", type=Path, default=DEFAULT_OBSERVED_PACK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top", type=int, default=250)
    parser.add_argument("--plan-days", type=int, default=28)
    args = parser.parse_args()

    airports_payload = json.loads(args.airport_index.read_text(encoding="utf-8"))
    contexts_payload = json.loads(args.context_index.read_text(encoding="utf-8"))
    observed_payload = _read_json(args.observed_pack)

    airports = _airport_lookup(airports_payload)
    observed_pairs = _observed_pairs(observed_payload)
    candidate_routes = _candidate_routes(contexts_payload, airports, observed_pairs)
    scored = sorted((_score_gap(route, airports) for route in candidate_routes), key=lambda item: item["score"], reverse=True)

    khh_gaps = [item for item in scored if item["origin"] == "KHH" or item["destination"] == "KHH"]
    country_gaps = _country_gaps(scored, airports)
    output = {
        "schemaVersion": 1,
        "source": {
            "candidateRoutes": "shared/offline-packs/core-global/aviation-context-index.json routeGraph",
            "observedRoutes": str(args.observed_pack.relative_to(PROJECT)),
        },
        "observedSummary": {
            "routes": len(observed_payload.get("routes", [])),
            "releaseUrls": len(observed_payload.get("source", {}).get("releaseUrls", [])),
            "stats": observed_payload.get("stats", {}),
        },
        "gapSummary": {
            "candidateRoutes": len(candidate_routes),
            "topReturned": min(args.top, len(scored)),
            "khhGaps": len(khh_gaps),
            "topGapCountries": country_gaps[:20],
        },
        "priorityGaps": scored[: args.top],
        "khhPriorityGaps": khh_gaps[:100],
        "downloadPlan": _download_plan(observed_payload, args.plan_days),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "gaps": len(candidate_routes), "khhGaps": len(khh_gaps)}, indent=2))
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def _airport_lookup(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    airports = {}
    for airport in payload.get("airports", []):
        iata = airport.get("iataCode")
        if not iata:
            continue
        airports[iata] = airport
    return airports


def _observed_pairs(payload: dict[str, Any]) -> set[tuple[str, str]]:
    pairs = set()
    for route in payload.get("routes", []):
        origin = route.get("originIata")
        destination = route.get("destinationIata")
        if origin and destination:
            pairs.add((origin, destination))
    return pairs


def _candidate_routes(
    payload: dict[str, Any],
    airports: dict[str, dict[str, Any]],
    observed_pairs: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    routes = []
    for context in payload.get("contexts", []):
        origin = context.get("iataCode")
        if origin not in airports:
            continue
        route_graph = context.get("routeGraph") or {}
        for destination in route_graph.get("destinations") or route_graph.get("topDestinations") or []:
            code = destination.get("code")
            if code not in airports or (origin, code) in observed_pairs:
                continue
            routes.append(
                {
                    "origin": origin,
                    "destination": code,
                    "openFlightsCount": int(destination.get("count") or 0),
                    "aircraftTypes": sorted(set(destination.get("aircraftTypes") or [])),
                    "airlines": sorted(set(route_graph.get("airlines") or [])),
                }
            )
    return routes


def _score_gap(route: dict[str, Any], airports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    origin = airports[route["origin"]]
    destination = airports[route["destination"]]
    score = 0
    score += route["openFlightsCount"] * 40
    score += _airport_weight(origin) + _airport_weight(destination)
    score += min(len(route["airlines"]), 8) * 8
    score += min(len(route["aircraftTypes"]), 6) * 6
    if origin.get("countryCode") != destination.get("countryCode"):
        score += 30
    pair = (route["origin"], route["destination"])
    reverse_pair = (route["destination"], route["origin"])
    if pair in IMPORTANT_TW_ROUTES or reverse_pair in IMPORTANT_TW_ROUTES:
        score += 1000
    elif route["origin"] == "KHH" or route["destination"] == "KHH":
        score += 600
    elif origin.get("countryCode") == "TW" or destination.get("countryCode") == "TW":
        score += 180
    return {
        **route,
        "score": score,
        "originCountry": origin.get("countryCode"),
        "destinationCountry": destination.get("countryCode"),
        "originType": origin.get("type"),
        "destinationType": destination.get("type"),
        "originName": origin.get("name"),
        "destinationName": destination.get("name"),
    }


def _airport_weight(airport: dict[str, Any]) -> int:
    score = 0
    if airport.get("scheduledService"):
        score += 35
    airport_type = airport.get("type")
    if airport_type == "large_airport":
        score += 80
    elif airport_type == "medium_airport":
        score += 45
    elif airport_type == "small_airport":
        score += 10
    longest = airport.get("longestRunwayFeet") or 0
    if longest >= 10000:
        score += 20
    elif longest >= 7000:
        score += 10
    return score


def _country_gaps(gaps: list[dict[str, Any]], airports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    weighted: Counter[str] = Counter()
    for gap in gaps:
        for code in (gap["origin"], gap["destination"]):
            country = airports[code].get("countryCode") or "??"
            counter[country] += 1
            weighted[country] += gap["score"]
    return [
        {"country": country, "gaps": count, "weightedScore": weighted[country]}
        for country, count in counter.most_common()
    ]


def _download_plan(observed_payload: dict[str, Any], plan_days: int) -> dict[str, Any]:
    present_dates = sorted(_observed_dates(observed_payload))
    if not present_dates:
        return {"presentDates": [], "recommendedDates": []}
    latest = date.fromisoformat(present_dates[-1])
    present = {date.fromisoformat(item) for item in present_dates}
    recommended = []
    cursor = latest - timedelta(days=1)
    while len(recommended) < plan_days:
        if cursor not in present:
            recommended.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return {
        "strategy": "Backfill missing recent days first, then evaluate marginal popular-gap hits after each date.",
        "presentDates": present_dates,
        "recommendedDates": recommended,
    }


def _observed_dates(payload: dict[str, Any]) -> set[str]:
    dates = set()
    for route in payload.get("routes", []):
        for variant in route.get("variants", []):
            for value in variant.get("dateRange") or []:
                if isinstance(value, str) and len(value) == 10:
                    dates.add(value)
    return dates


if __name__ == "__main__":
    raise SystemExit(main())
