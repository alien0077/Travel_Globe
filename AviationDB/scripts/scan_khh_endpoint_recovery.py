#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from aviationdb.observed_routes import (  # noqa: E402
    Airport,
    AirportIndex,
    BuildOptions,
    TracePoint,
    fetch_preferred_releases,
    haversine_km,
    iter_trace_payloads_from_split_tar,
    parse_trace_points,
    route_distance_km,
    sample_from_leg,
    split_legs,
)
from build_observed_routes_range import _download_with_curl  # noqa: E402


DEFAULT_AIRPORT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "airports-index.json"
DEFAULT_WORK_DIR = Path("/private/tmp/travel-globe-adsblol-diagnostics")
DEFAULT_OUTPUT_DIR = PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "diagnostics"
DISTANCE_BUCKETS_KM = (30, 60, 100, 150, 300, 500)
TARGET_DESTINATIONS = {"NRT", "HND", "KIX", "OKA", "HKG", "ICN", "PUS", "BKK", "DMK", "SIN", "MNL"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a daily ADSB.lol release for KHH endpoint recovery evidence.")
    parser.add_argument("--date", required=True, help="ADSB.lol preferred release date, YYYY-MM-DD.")
    parser.add_argument("--airport", default="KHH", help="Target IATA airport to diagnose.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-examples", type=int, default=180)
    parser.add_argument("--max-airport-km", type=float, default=150)
    parser.add_argument("--min-points", type=int, default=8)
    parser.add_argument("--min-route-km", type=float, default=120)
    parser.add_argument("--max-trace-gap-s", type=float, default=2700)
    parser.add_argument("--max-track-detour-ratio", type=float, default=2.6)
    args = parser.parse_args()

    options = BuildOptions(
        min_points=args.min_points,
        min_route_km=args.min_route_km,
        max_airport_km=args.max_airport_km,
        max_trace_gap_s=args.max_trace_gap_s,
        max_track_detour_ratio=args.max_track_detour_ratio,
    )
    airport_index = AirportIndex.from_json(args.airport_index)
    airports = {airport.iata: airport for airport in airport_index.airports}
    target = airports.get(args.airport.strip().upper())
    if target is None:
        raise SystemExit(f"Unknown airport: {args.airport}")

    releases = fetch_preferred_releases(args.year)
    entry = releases.get(args.date)
    if entry is None:
        raise SystemExit(f"No ADSB.lol preferred release found for {args.date}.")
    release_dir = args.work_dir / entry.date
    release_dir.mkdir(parents=True, exist_ok=True)
    parts = [_download_with_curl(url, release_dir) for url in entry.urls]

    result = scan_khh_endpoint_recovery(
        parts=parts,
        date=args.date,
        target=target,
        airport_index=airport_index,
        options=options,
        max_examples=args.max_examples,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{args.date}-{target.iata}-endpoint-recovery.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": result["summary"]}, ensure_ascii=False, indent=2))
    return 0


def scan_khh_endpoint_recovery(
    parts: list[Path],
    date: str,
    target: Airport,
    airport_index: AirportIndex,
    options: BuildOptions,
    max_examples: int,
) -> dict[str, Any]:
    summary: Counter[str] = Counter()
    distance_buckets: Counter[str] = Counter()
    endpoint_buckets: Counter[str] = Counter()
    current_routes: Counter[str] = Counter()
    reject_reasons: Counter[str] = Counter()
    top_callsigns: Counter[str] = Counter()
    missed_candidates: list[dict[str, Any]] = []
    khh_nearby_examples: list[dict[str, Any]] = []

    for source_name, payload in iter_trace_payloads_from_split_tar(parts):
        summary["traces_seen"] += 1
        try:
            trace = json.loads(payload)
            points = parse_trace_points(trace)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            reject_reasons["parse_error"] += 1
            continue
        legs = split_legs(points, options)
        if not legs:
            continue
        for leg in legs:
            summary["legs_seen"] += 1
            profile = _khh_profile(leg, target)
            if profile["minDistanceKm"] > 500 and min(profile["firstDistanceKm"], profile["lastDistanceKm"]) > 500:
                continue
            summary["khh_related_legs"] += 1
            distance_buckets[_bucket(profile["minDistanceKm"])] += 1
            endpoint_buckets[f"first:{_bucket(profile['firstDistanceKm'])}"] += 1
            endpoint_buckets[f"last:{_bucket(profile['lastDistanceKm'])}"] += 1

            diagnosis = _diagnose_assignment(leg, trace, source_name, target, airport_index, options)
            route_key = diagnosis.get("routeKey") or "unassigned"
            current_routes[route_key] += 1
            reject_reasons[diagnosis["reason"]] += 1
            callsign = diagnosis.get("callsign")
            if callsign:
                top_callsigns[callsign] += 1

            item = {**diagnosis, **profile}
            if len(khh_nearby_examples) < max_examples:
                khh_nearby_examples.append(item)
            if _is_missed_khh_candidate(item, target.iata):
                summary["missed_khh_endpoint_candidates"] += 1
                _push_scored(missed_candidates, item, max_examples * 2)

    return {
        "schemaVersion": 1,
        "date": date,
        "targetAirport": {"iata": target.iata, "icao": target.icao, "name": target.name},
        "options": options.__dict__,
        "summary": dict(summary),
        "khhNearbyLegs": {
            "minDistanceBuckets": distance_buckets.most_common(),
            "endpointDistanceBuckets": endpoint_buckets.most_common(),
        },
        "missedKhhEndpointCandidates": sorted(missed_candidates, key=lambda item: item["recoveryScore"], reverse=True),
        "currentRouteAssignments": current_routes.most_common(80),
        "rejectReasons": reject_reasons.most_common(),
        "topCallsigns": top_callsigns.most_common(100),
        "examples": khh_nearby_examples,
    }


def _khh_profile(leg: list[TracePoint], target: Airport) -> dict[str, Any]:
    distances = [haversine_km(point.lat, point.lon, target.lat, target.lon) for point in leg]
    min_index, min_distance = min(enumerate(distances), key=lambda item: item[1])
    first_distance = distances[0]
    last_distance = distances[-1]
    return {
        "minDistanceKm": round(min_distance, 1),
        "minDistanceElapsedS": leg[min_index].elapsed_s,
        "firstDistanceKm": round(first_distance, 1),
        "lastDistanceKm": round(last_distance, 1),
        "closestPoint": _point_payload(leg[min_index], target),
    }


def _diagnose_assignment(
    leg: list[TracePoint],
    trace: dict[str, Any],
    source_name: str,
    target: Airport,
    airport_index: AirportIndex,
    options: BuildOptions,
) -> dict[str, Any]:
    first = leg[0]
    last = leg[-1]
    nearest_first = airport_index.nearest(first.lat, first.lon, options.max_airport_km)
    nearest_last = airport_index.nearest(last.lat, last.lon, options.max_airport_km)
    distance = route_distance_km([(point.lat, point.lon) for point in leg])
    reason = "accepted"
    direct = None
    detour_ratio = None
    if nearest_first is None:
        reason = "origin_endpoint_not_near_index_airport"
    elif nearest_last is None:
        reason = "destination_endpoint_not_near_index_airport"
    elif nearest_first.airport.iata == nearest_last.airport.iata:
        reason = "same_origin_destination_airport"
    else:
        direct = haversine_km(
            nearest_first.airport.lat,
            nearest_first.airport.lon,
            nearest_last.airport.lat,
            nearest_last.airport.lon,
        )
        detour_ratio = distance / direct if direct > 0 else None
        if direct < options.min_route_km or distance < options.min_route_km:
            reason = "route_too_short"
        elif detour_ratio is not None and detour_ratio > options.max_track_detour_ratio:
            reason = "track_detour_ratio_too_high"
    sample = sample_from_leg(leg, airport_index, options, trace.get("icao"), None, source_name)
    route_key = sample.route_key if sample is not None else _route_key(nearest_first, nearest_last)
    callsign = _leg_callsign(leg) or trace.get("flight")
    first_payload = _point_payload(first, target)
    last_payload = _point_payload(last, target)
    return {
        "reason": reason,
        "routeKey": route_key,
        "callsign": callsign,
        "sourceFile": source_name,
        "points": len(leg),
        "distanceKm": round(distance, 1),
        "directKm": round(direct, 1) if direct is not None else None,
        "detourRatio": round(detour_ratio, 3) if detour_ratio is not None else None,
        "nearestFirst": _nearest_payload(nearest_first),
        "nearestLast": _nearest_payload(nearest_last),
        "firstPoint": first_payload,
        "lastPoint": last_payload,
        "recoveryScore": _recovery_score(route_key, reason, first_payload, last_payload),
    }


def _is_missed_khh_candidate(item: dict[str, Any], target_iata: str) -> bool:
    route_key = item.get("routeKey") or ""
    if target_iata in route_key.split("-"):
        return False
    if min(item["firstDistanceKm"], item["lastDistanceKm"]) <= 500:
        return True
    if item["minDistanceKm"] <= 150 and item["distanceKm"] >= 120:
        return True
    return False


def _recovery_score(
    route_key: str | None,
    reason: str,
    first_point: dict[str, Any],
    last_point: dict[str, Any],
) -> float:
    first_km = first_point["distanceToTargetKm"]
    last_km = last_point["distanceToTargetKm"]
    score = 1000 - min(first_km, last_km) * 1.2
    if route_key:
        origin, _, destination = route_key.partition("-")
        if origin in {"TPE", "RMQ", "TSA", "OGN", "ISG"} or destination in {"TPE", "RMQ", "TSA", "OGN", "ISG"}:
            score += 180
        if origin in TARGET_DESTINATIONS or destination in TARGET_DESTINATIONS:
            score += 120
    if reason != "accepted":
        score += 80
    return round(score, 2)


def _bucket(distance_km: float) -> str:
    for ceiling in DISTANCE_BUCKETS_KM:
        if distance_km <= ceiling:
            return f"<= {ceiling} km"
    return "> 500 km"


def _push_scored(items: list[dict[str, Any]], item: dict[str, Any], limit: int) -> None:
    items.append(item)
    if len(items) > limit * 3:
        items.sort(key=lambda value: value["recoveryScore"], reverse=True)
        del items[limit:]


def _point_payload(point: TracePoint, target: Airport) -> dict[str, Any]:
    return {
        "elapsedS": point.elapsed_s,
        "lat": round(point.lat, 5),
        "lon": round(point.lon, 5),
        "altitudeFt": point.altitude_ft,
        "trackDeg": point.track_deg,
        "distanceToTargetKm": round(haversine_km(point.lat, point.lon, target.lat, target.lon), 1),
    }


def _nearest_payload(nearest: Any) -> dict[str, Any] | None:
    if nearest is None:
        return None
    return {
        "iata": nearest.airport.iata,
        "icao": nearest.airport.icao,
        "name": nearest.airport.name,
        "distanceKm": round(nearest.distance_km, 1),
    }


def _route_key(first: Any, last: Any) -> str | None:
    if first is None or last is None:
        return None
    return f"{first.airport.iata}-{last.airport.iata}"


def _leg_callsign(points: list[TracePoint]) -> str | None:
    for point in points:
        if point.callsign:
            return point.callsign
    return None


if __name__ == "__main__":
    raise SystemExit(main())
