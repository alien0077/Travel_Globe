#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
DEFAULT_AIRPORT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "airports-index.json"
DEFAULT_CONTEXT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "aviation-context-index.json"
DEFAULT_OBSERVED_PACK = (
    PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "observed-routes.global.json.gz"
)
DEFAULT_OUTPUT = (
    PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "route-source-fusion.global.json"
)
DEFAULT_SUSPICIOUS_OUTPUT = (
    PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "suspicious-airports.global.json"
)


SOURCE_REGISTRY = {
    "observed_adsb": {
        "label": "Observed ADS-B track",
        "defaultConfidence": 0.95,
        "offlineRedistribution": "private_pack_only",
    },
    "recovered_endpoint": {
        "label": "Observed ADS-B track with endpoint recovery",
        "defaultConfidence": 0.82,
        "offlineRedistribution": "private_pack_only",
    },
    "static_route_graph": {
        "label": "OpenFlights historical airline route graph",
        "defaultConfidence": 0.62,
        "offlineRedistribution": "allowed_with_odbl_provenance",
    },
    "airport_pair_fallback": {
        "label": "Airport-pair fallback route",
        "defaultConfidence": 0.48,
        "offlineRedistribution": "derived_private_pack",
    },
    "airport_connectivity_fallback": {
        "label": "Synthetic airport connectivity fallback",
        "defaultConfidence": 0.25,
        "offlineRedistribution": "derived_private_pack",
        "note": "Only guarantees a scheduled airport can be connected offline; it is not evidence that the airport pair is a real operated route.",
    },
    "adsbdb_targeted": {
        "label": "ADSBDB targeted callsign/flightroute lookup",
        "defaultConfidence": 0.55,
        "offlineRedistribution": "manual_review_required",
        "note": "ADSBDB documents say flightroute data may not be copied or incorporated into other databases without permission.",
    },
    "airportroutes_targeted": {
        "label": "AirportRoutes targeted airport-pair lookup",
        "defaultConfidence": 0.7,
        "offlineRedistribution": "manual_review_required",
        "note": "AirportRoutes public site advertises free tracking for 3 airports and FlightAware-derived route data; do not bulk ingest without terms review.",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build route-source fusion and suspicious-airport reports.")
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--context-index", type=Path, default=DEFAULT_CONTEXT_INDEX)
    parser.add_argument("--observed-pack", type=Path, default=DEFAULT_OBSERVED_PACK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--suspicious-output", type=Path, default=DEFAULT_SUSPICIOUS_OUTPUT)
    parser.add_argument("--suspicious-min-score", type=int, default=10)
    parser.add_argument("--fallback-min-score", type=int, default=20)
    parser.add_argument("--ensure-all-airports", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    airports_payload = json.loads(args.airport_index.read_text(encoding="utf-8"))
    context_payload = json.loads(args.context_index.read_text(encoding="utf-8"))
    observed_payload = _read_json(args.observed_pack)

    airports = _airport_lookup(airports_payload)
    observed_routes = _observed_routes(observed_payload)
    static_routes = _static_route_graph_routes(context_payload, airports)
    route_records = _merge_route_records(static_routes, observed_routes, args.fallback_min_score)
    connectivity_routes = []
    if args.ensure_all_airports:
        route_records, connectivity_routes = _ensure_all_airport_connectivity(airports, route_records)
    suspicious_airports = _suspicious_airports(airports, context_payload, observed_routes, args.suspicious_min_score)

    fusion = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourceRegistry": SOURCE_REGISTRY,
        "summary": {
            "airports": len(airports),
            "observedRoutes": len(observed_routes),
            "staticRouteGraphRoutes": len(static_routes),
            "airportConnectivityFallbackRoutes": len(connectivity_routes),
            "fusedRoutes": len(route_records),
            "airportsWithAnyRoute": len(_route_endpoints(route_records)),
            "suspiciousAirports": len(suspicious_airports),
        },
        "routes": route_records,
    }
    suspicious = {
        "schemaVersion": 1,
        "generatedAt": fusion["generatedAt"],
        "method": "route_graph_activity_vs_observed_endpoint_count",
        "summary": {
            "airports": len(airports),
            "suspiciousAirports": len(suspicious_airports),
            "zeroObservedLargeAirports": sum(
                1 for item in suspicious_airports if item["observedEndpointSamples"] == 0 and item["airportType"] == "large_airport"
            ),
        },
        "airports": suspicious_airports,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fusion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.suspicious_output.parent.mkdir(parents=True, exist_ok=True)
    args.suspicious_output.write_text(json.dumps(suspicious, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "suspiciousOutput": str(args.suspicious_output),
                "summary": fusion["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
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
        if not airport.get("scheduledService"):
            continue
        if airport.get("type") not in {"large_airport", "medium_airport", "small_airport"}:
            continue
        airports[iata] = airport
    return airports


def _observed_routes(payload: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    routes = {}
    for route in payload.get("routes", []):
        origin = route.get("originIata")
        destination = route.get("destinationIata")
        if not origin or not destination:
            continue
        routes[(origin, destination)] = {
            "origin": origin,
            "destination": destination,
            "sampleCount": route.get("sampleCount") or 0,
            "variantCount": route.get("variantCount") or 0,
            "representative": route.get("representative"),
        }
    return routes


def _static_route_graph_routes(
    payload: dict[str, Any],
    airports: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    routes = {}
    for context in payload.get("contexts", []):
        origin = context.get("iataCode")
        if origin not in airports:
            continue
        route_graph = context.get("routeGraph") or {}
        for destination in route_graph.get("destinations") or route_graph.get("topDestinations") or []:
            code = destination.get("code")
            if code not in airports:
                continue
            routes[(origin, code)] = {
                "origin": origin,
                "destination": code,
                "openFlightsCount": int(destination.get("count") or 0),
                "aircraftTypes": sorted(set(destination.get("aircraftTypes") or [])),
                "airlines": sorted(set(route_graph.get("airlines") or [])),
            }
    return routes


def _merge_route_records(
    static_routes: dict[tuple[str, str], dict[str, Any]],
    observed_routes: dict[tuple[str, str], dict[str, Any]],
    fallback_min_score: int,
) -> list[dict[str, Any]]:
    records = []
    pairs = sorted(set(static_routes) | set(observed_routes))
    for pair in pairs:
        static = static_routes.get(pair)
        observed = observed_routes.get(pair)
        sources = []
        if observed:
            sources.append(
                {
                    "type": "observed_adsb",
                    "confidence": SOURCE_REGISTRY["observed_adsb"]["defaultConfidence"],
                    "sampleCount": observed["sampleCount"],
                    "variantCount": observed["variantCount"],
                }
            )
        if static:
            sources.append(
                {
                    "type": "static_route_graph",
                    "confidence": SOURCE_REGISTRY["static_route_graph"]["defaultConfidence"],
                    "openFlightsCount": static["openFlightsCount"],
                    "aircraftTypes": static["aircraftTypes"],
                    "airlines": static["airlines"],
                }
            )
        score = _route_score(static, observed)
        if not observed and static and score >= fallback_min_score:
            sources.append(
                {
                    "type": "airport_pair_fallback",
                    "confidence": SOURCE_REGISTRY["airport_pair_fallback"]["defaultConfidence"],
                    "reason": "static_route_exists_but_no_observed_adsb_route",
                }
            )
        best_source = max(sources, key=lambda item: item["confidence"])["type"] if sources else "unknown"
        records.append(
            {
                "id": f"{pair[0]}-{pair[1]}",
                "originIata": pair[0],
                "destinationIata": pair[1],
                "bestSource": best_source,
                "routeScore": score,
                "hasObservedAdsb": observed is not None,
                "requiresFallbackShape": observed is None,
                "sources": sources,
            }
        )
    return records


def _ensure_all_airport_connectivity(
    airports: dict[str, dict[str, Any]],
    route_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    existing_pairs = {(route["originIata"], route["destinationIata"]) for route in route_records}
    connected = _route_endpoints(route_records)
    missing = sorted(code for code in airports if code not in connected)
    connected_airports = [airports[code] for code in sorted(connected) if code in airports]
    new_routes: list[dict[str, Any]] = []
    for code in missing:
        airport = airports[code]
        target = _nearest_connected_airport(airport, connected_airports)
        if target is None:
            continue
        pair = (code, target["iataCode"])
        reverse_pair = (target["iataCode"], code)
        distance_km = round(_distance_km(airport, target), 1)
        reason = "nearest_connected_airport_same_country" if airport.get("countryCode") == target.get("countryCode") else "nearest_connected_airport_global"
        for origin, destination in [pair, reverse_pair]:
            if (origin, destination) in existing_pairs:
                continue
            existing_pairs.add((origin, destination))
            record = {
                "id": f"{origin}-{destination}",
                "originIata": origin,
                "destinationIata": destination,
                "bestSource": "airport_connectivity_fallback",
                "routeScore": 1,
                "hasObservedAdsb": False,
                "requiresFallbackShape": True,
                "sources": [
                    {
                        "type": "airport_connectivity_fallback",
                        "confidence": SOURCE_REGISTRY["airport_connectivity_fallback"]["defaultConfidence"],
                        "reason": reason,
                        "anchorIata": target["iataCode"],
                        "distanceKm": distance_km,
                    }
                ],
            }
            route_records.append(record)
            new_routes.append(record)
    return sorted(route_records, key=lambda route: route["id"]), new_routes


def _route_endpoints(route_records: list[dict[str, Any]]) -> set[str]:
    endpoints: set[str] = set()
    for route in route_records:
        endpoints.add(route["originIata"])
        endpoints.add(route["destinationIata"])
    return endpoints


def _nearest_connected_airport(
    airport: dict[str, Any],
    connected_airports: list[dict[str, Any]],
) -> dict[str, Any] | None:
    same_country = [candidate for candidate in connected_airports if candidate.get("countryCode") == airport.get("countryCode")]
    candidates = same_country or connected_airports
    best: tuple[float, dict[str, Any]] | None = None
    for candidate in candidates:
        distance = _distance_km(airport, candidate)
        if best is None or distance < best[0]:
            best = (distance, candidate)
    return best[1] if best else None


def _distance_km(a: dict[str, Any], b: dict[str, Any]) -> float:
    lat1 = math.radians(float(a["latitude"]))
    lon1 = math.radians(float(a["longitude"]))
    lat2 = math.radians(float(b["latitude"]))
    lon2 = math.radians(float(b["longitude"]))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1, math.sqrt(hav)))


def _route_score(static: dict[str, Any] | None, observed: dict[str, Any] | None) -> int:
    score = 0
    if observed:
        score += min(observed["sampleCount"], 100)
    if static:
        score += static["openFlightsCount"] * 8
        score += min(len(static["airlines"]), 8) * 4
        score += min(len(static["aircraftTypes"]), 6) * 3
    return score


def _suspicious_airports(
    airports: dict[str, dict[str, Any]],
    context_payload: dict[str, Any],
    observed_routes: dict[tuple[str, str], dict[str, Any]],
    min_score: int,
) -> list[dict[str, Any]]:
    observed_endpoint_samples: Counter[str] = Counter()
    observed_endpoint_routes: Counter[str] = Counter()
    for (origin, destination), route in observed_routes.items():
        sample_count = route.get("sampleCount") or 1
        observed_endpoint_samples[origin] += sample_count
        observed_endpoint_samples[destination] += sample_count
        observed_endpoint_routes[origin] += 1
        observed_endpoint_routes[destination] += 1

    rows = []
    for context in context_payload.get("contexts", []):
        code = context.get("iataCode")
        airport = airports.get(code)
        if not airport:
            continue
        route_graph = context.get("routeGraph") or {}
        destinations = route_graph.get("destinations") or route_graph.get("topDestinations") or []
        outgoing = int(route_graph.get("outgoingRoutes") or 0)
        incoming = int(route_graph.get("incomingRoutes") or 0)
        graph_score = outgoing + incoming + len(destinations) * 2
        if graph_score < min_score:
            continue
        samples = observed_endpoint_samples[code]
        observed_count = observed_endpoint_routes[code]
        if samples > 0 and observed_count > 3:
            continue
        rows.append(
            {
                "iata": code,
                "icao": airport.get("icaoCode"),
                "name": airport.get("name"),
                "countryCode": airport.get("countryCode"),
                "airportType": airport.get("type"),
                "routeGraphScore": graph_score,
                "routeGraphOutgoing": outgoing,
                "routeGraphIncoming": incoming,
                "routeGraphDestinations": len(destinations),
                "observedEndpointRoutes": observed_count,
                "observedEndpointSamples": samples,
                "severity": _severity(graph_score, samples),
            }
        )
    severity_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    return sorted(rows, key=lambda item: (severity_rank[item["severity"]], item["routeGraphScore"]), reverse=True)


def _severity(graph_score: int, observed_samples: int) -> str:
    if graph_score >= 200 and observed_samples == 0:
        return "critical"
    if graph_score >= 80 and observed_samples == 0:
        return "high"
    if graph_score >= 30 and observed_samples <= 3:
        return "medium"
    return "low"


if __name__ == "__main__":
    raise SystemExit(main())
