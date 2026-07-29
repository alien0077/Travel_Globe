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


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose why a target observed route gap was not accepted.")
    parser.add_argument("--date", required=True, help="ADSB.lol preferred release date, YYYY-MM-DD.")
    parser.add_argument("--origin", required=True, help="Target origin IATA.")
    parser.add_argument("--destination", required=True, help="Target destination IATA.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--probe-km", type=float, default=350)
    parser.add_argument("--cleanup-downloads", action="store_true")
    parser.add_argument("--max-examples", type=int, default=80)
    parser.add_argument("--min-points", type=int, default=8)
    parser.add_argument("--min-route-km", type=float, default=120)
    parser.add_argument("--max-airport-km", type=float, default=150)
    parser.add_argument("--max-trace-gap-s", type=float, default=2700)
    parser.add_argument("--simplify-tolerance-km", type=float, default=8)
    parser.add_argument("--max-points-per-route", type=int, default=96)
    parser.add_argument("--signature-samples", type=int, default=14)
    parser.add_argument("--signature-quantum-deg", type=float, default=0.5)
    parser.add_argument("--max-track-detour-ratio", type=float, default=2.6)
    args = parser.parse_args()

    origin_code = args.origin.strip().upper()
    destination_code = args.destination.strip().upper()
    options = BuildOptions(
        min_points=args.min_points,
        min_route_km=args.min_route_km,
        max_airport_km=args.max_airport_km,
        max_trace_gap_s=args.max_trace_gap_s,
        simplify_tolerance_km=args.simplify_tolerance_km,
        max_points_per_route=args.max_points_per_route,
        signature_samples=args.signature_samples,
        signature_quantum_deg=args.signature_quantum_deg,
        max_track_detour_ratio=args.max_track_detour_ratio,
    )
    airport_index = AirportIndex.from_json(args.airport_index)
    airports = {airport.iata: airport for airport in airport_index.airports}
    origin_airport = airports.get(origin_code)
    destination_airport = airports.get(destination_code)
    if origin_airport is None or destination_airport is None:
        raise SystemExit(f"Unknown target airport(s): {origin_code}, {destination_code}")

    releases = fetch_preferred_releases(args.year)
    entry = releases.get(args.date)
    if entry is None:
        raise SystemExit(f"No ADSB.lol preferred release found for {args.date}.")

    release_dir = args.work_dir / entry.date
    release_dir.mkdir(parents=True, exist_ok=True)
    parts = [_download_with_curl(url, release_dir) for url in entry.urls]
    result = diagnose_parts(
        parts=parts,
        date=args.date,
        origin=origin_airport,
        destination=destination_airport,
        airport_index=airport_index,
        options=options,
        probe_km=args.probe_km,
        max_examples=args.max_examples,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{args.date}-{origin_code}-{destination_code}.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.cleanup_downloads:
        for part in parts:
            part.unlink(missing_ok=True)
    print(json.dumps({"output": str(output), "summary": result["summary"]}, ensure_ascii=False, indent=2))
    return 0


def diagnose_parts(
    parts: list[Path],
    date: str,
    origin: Airport,
    destination: Airport,
    airport_index: AirportIndex,
    options: BuildOptions,
    probe_km: float,
    max_examples: int,
) -> dict[str, Any]:
    summary: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    accepted_routes: Counter[str] = Counter()
    callsigns: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []

    for source_name, payload in iter_trace_payloads_from_split_tar(parts):
        summary["traces_seen"] += 1
        try:
            trace = json.loads(payload)
            points = parse_trace_points(trace)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            reasons["parse_error"] += 1
            continue
        if not points:
            reasons["no_points"] += 1
            continue
        legs = split_legs(points, options)
        if not legs:
            if _trace_near_target(points, origin, destination, probe_km):
                summary["near_target_traces_without_legs"] += 1
            continue
        for leg in legs:
            summary["legs_seen"] += 1
            if not _trace_near_target(leg, origin, destination, probe_km):
                continue
            summary["near_target_legs"] += 1
            diagnosis = _diagnose_leg(
                leg=leg,
                trace=trace,
                source_name=source_name,
                origin=origin,
                destination=destination,
                airport_index=airport_index,
                options=options,
            )
            reasons[diagnosis["reason"]] += 1
            route_key = diagnosis.get("routeKey")
            if route_key:
                accepted_routes[route_key] += 1
            callsign = diagnosis.get("callsign")
            if callsign:
                callsigns[callsign] += 1
            if len(examples) < max_examples:
                examples.append(diagnosis)

    return {
        "schemaVersion": 1,
        "date": date,
        "target": {"origin": origin.iata, "destination": destination.iata},
        "options": options.__dict__,
        "probeKm": probe_km,
        "summary": dict(summary),
        "rejectReasons": reasons.most_common(),
        "acceptedRoutesNearTarget": accepted_routes.most_common(40),
        "callsignsNearTarget": callsigns.most_common(80),
        "examples": examples,
    }


def _diagnose_leg(
    leg: list[TracePoint],
    trace: dict[str, Any],
    source_name: str,
    origin: Airport,
    destination: Airport,
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
    return {
        "reason": reason,
        "routeKey": route_key,
        "callsign": callsign,
        "sourceFile": source_name,
        "points": len(leg),
        "distanceKm": round(distance, 1),
        "directKm": round(direct, 1) if direct is not None else None,
        "detourRatio": round(detour_ratio, 3) if detour_ratio is not None else None,
        "firstPoint": _point_payload(first, origin, destination),
        "lastPoint": _point_payload(last, origin, destination),
        "nearestFirst": _nearest_payload(nearest_first),
        "nearestLast": _nearest_payload(nearest_last),
    }


def _trace_near_target(points: list[TracePoint], origin: Airport, destination: Airport, probe_km: float) -> bool:
    for point in points:
        if haversine_km(point.lat, point.lon, origin.lat, origin.lon) <= probe_km:
            return True
        if haversine_km(point.lat, point.lon, destination.lat, destination.lon) <= probe_km:
            return True
    return False


def _point_payload(point: TracePoint, origin: Airport, destination: Airport) -> dict[str, Any]:
    return {
        "elapsedS": point.elapsed_s,
        "lat": round(point.lat, 5),
        "lon": round(point.lon, 5),
        "altitudeFt": point.altitude_ft,
        "trackDeg": point.track_deg,
        "distanceToOriginKm": round(haversine_km(point.lat, point.lon, origin.lat, origin.lon), 1),
        "distanceToDestinationKm": round(haversine_km(point.lat, point.lon, destination.lat, destination.lon), 1),
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
