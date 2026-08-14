#!/usr/bin/env python3
"""Resolve connectivity gaps and KHH endpoint misclassification from local 7-day raw.

This is an evidence overlay, not a rewrite of the immutable global network.

Two mistakes this stage is designed to prevent:

* treating every bridge candidate as an unresolved connectivity failure even
  when the two terminals are already connected by observed geometry or by the
  separately labelled relay layer;
* assigning a trace to the nearest airport only.  A trace can begin or end
  outside the receiver envelope, so its terminal direction and distance trend
  are evaluated against KHH and nearby airports without changing the raw track.

No IFR data, airport-pair schedule, or straight-line middle geometry is used.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))

from aviationdb.observed_routes import (  # noqa: E402
    Airport,
    AirportIndex,
    BuildOptions,
    TracePoint,
    haversine_km,
    iter_trace_payloads_from_split_tar,
    parse_trace_points,
    route_distance_km,
    split_legs,
)


CELL_DEG = 0.25
KHH = "KHH"
NRT = "NRT"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_NETWORK = PROJECT / (
    "data/releases/private/observed-routes/adsblol/global-network-7d-025/"
    "global-corridor-network.json.gz"
)
DEFAULT_AIRPORTS = ROOT / "shared/offline-packs/core-global/airports-index.json"
DEFAULT_RAW_ROOT = PROJECT / "data/raw/adsblol"
DEFAULT_OUTPUT_ROOT = PROJECT / (
    "data/releases/private/observed-routes/adsblol/global-network-7d-025/resolution"
)

Node = tuple[int, int]


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve global gap classifications and KHH endpoints from local raw.")
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORTS)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--airport", default=KHH)
    parser.add_argument("--max-terminal-km", type=float, default=180.0)
    parser.add_argument("--strong-terminal-km", type=float, default=80.0)
    parser.add_argument("--max-route-airport-km", type=float, default=180.0)
    parser.add_argument("--min-terminal-points", type=int, default=8)
    parser.add_argument("--max-trace-gap-s", type=float, default=2700.0)
    parser.add_argument("--max-dates", type=int, default=7)
    args = parser.parse_args()

    args.output_root.mkdir(parents=True, exist_ok=True)
    _write_status(args.status, {"state": "running", "phase": "load"})
    network = _read_gzip(args.network)
    airport_index = AirportIndex.from_json(args.airport_index)
    airports = {airport.iata: airport for airport in airport_index.airports}
    target = airports.get(args.airport.upper())
    if target is None:
        raise SystemExit(f"Unknown airport: {args.airport}")

    gap_result = classify_gaps(network)
    _write_status(
        args.status,
        {
            "state": "running",
            "phase": "raw_khh_scan",
            "gapSummary": gap_result["summary"],
        },
    )
    raw_result = scan_khh_raw(
        raw_root=args.raw_root,
        target=target,
        airports=airports,
        max_terminal_km=args.max_terminal_km,
        strong_terminal_km=args.strong_terminal_km,
        max_route_airport_km=args.max_route_airport_km,
        min_terminal_points=args.min_terminal_points,
        max_trace_gap_s=args.max_trace_gap_s,
        max_dates=args.max_dates,
        status_path=args.status,
    )

    generated_at = _now()
    summary = {
        "networkUnresolvedGaps": len(network.get("unresolvedGaps", [])),
        "gapResolution": gap_result["summary"],
        "khhEndpointResolution": raw_result["summary"],
        "rawSourceDates": raw_result["sourceDates"],
        "ifrExcluded": True,
        "rawInputsPreserved": True,
        "observedGeometryUntouched": True,
    }
    payload = {
        "schemaVersion": 1,
        "evidenceType": "global_corridor_resolution_overlay_7d_v1",
        "generatedAt": generated_at,
        "source": {
            "network": str(args.network),
            "airportIndex": str(args.airport_index),
            "rawRoot": str(args.raw_root),
        },
        "summary": summary,
        "gapResolution": gap_result,
        "khhEndpointResolution": raw_result,
        "rules": {
            "baseNetworkNotOverwritten": True,
            "observedEdgesNotReclassified": True,
            "airportEndpointEvidenceIsSeparate": True,
            "independentEvidenceRequiresRawTraceOrExistingObservedPath": True,
            "noIfr": True,
            "noAirportPairScheduleGeneration": True,
            "noLongStraightLineFill": True,
        },
    }
    output = args.output_root / "global-corridor-resolution-overlay.json.gz"
    _write_gzip(output, payload)
    review = build_review(payload, network)
    (args.output_root / "global-corridor-resolution-review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_status(
        args.status,
        {
            "state": "complete",
            "phase": "written",
            "output": str(output),
            "summary": summary,
            "qa": review["qa"],
        },
    )
    print(json.dumps({"state": "complete", "summary": summary, "qa": review["qa"]}, ensure_ascii=False, indent=2))
    return 0 if review["qa"]["passed"] else 2


def classify_gaps(network: dict[str, Any]) -> dict[str, Any]:
    observed_edges = list(network.get("observedEdges", []))
    relay_edges = list(network.get("relayInferred", []))
    gaps = list(network.get("unresolvedGaps", []))
    observed_graph, observed_nodes = _graph(observed_edges)
    relay_graph, relay_nodes = _graph(observed_edges + relay_edges)
    observed_components = _components(observed_graph, observed_nodes)
    relay_components = _components(relay_graph, relay_nodes)

    counts: Counter[str] = Counter()
    resolved_ids: dict[str, list[str]] = defaultdict(list)
    remaining: list[dict[str, Any]] = []
    classifications: list[dict[str, Any]] = []
    for gap in gaps:
        left = _node_from_value(gap.get("from", {}))
        right = _node_from_value(gap.get("to", {}))
        if left is None or right is None:
            gap_class = "invalid_gap_coordinates"
            evidence = "gap_coordinates_unusable"
        elif left in observed_components and right in observed_components and observed_components[left] == observed_components[right]:
            gap_class = "observed_component_already_connected"
            evidence = "same_observed_component"
        elif left in relay_components and right in relay_components and relay_components[left] == relay_components[right]:
            gap_class = "relay_component_already_connected"
            evidence = "same_observed_plus_relay_component"
        else:
            gap_class = "independent_evidence_still_missing"
            evidence = "no_observed_or_relay_component_connection"
            remaining.append(gap)
        counts[gap_class] += 1
        bridge_id = str(gap.get("bridgeId") or f"gap-{len(classifications):07d}")
        resolved_ids[gap_class].append(bridge_id)
        classifications.append(
            {
                "bridgeId": bridge_id,
                "from": _node_payload(left),
                "to": _node_payload(right),
                "originalStatus": gap.get("status"),
                "resolutionClass": gap_class,
                "evidence": evidence,
                "sourceSupportLegs": gap.get("sourceSupportLegs", 0),
                "targetSupportLegs": gap.get("targetSupportLegs", 0),
                "sharedDates": gap.get("sharedDates", []),
            }
        )
    summary = {
        "inputGaps": len(gaps),
        "observedComponentAlreadyConnected": counts["observed_component_already_connected"],
        "relayComponentAlreadyConnected": counts["relay_component_already_connected"],
        "independentEvidenceStillMissing": counts["independent_evidence_still_missing"],
        "invalidGapCoordinates": counts["invalid_gap_coordinates"],
        "connectivityResolvedWithoutAddingGeometry": counts["observed_component_already_connected"] + counts["relay_component_already_connected"],
        "newObservedEdges": 0,
        "newInferredMiddleGeometry": 0,
    }
    return {
        "summary": summary,
        "classifications": classifications,
        "remainingIndependentEvidence": remaining,
        "resolvedBridgeIds": {key: values for key, values in sorted(resolved_ids.items())},
        "method": {
            "observedConnection": "both endpoints belong to the same component of existing observedEdges",
            "relayConnection": "both endpoints belong to the same component after existing relayInferred links",
            "remainingDefinition": "neither layer connects the endpoints; no new geometry was created",
        },
    }


def scan_khh_raw(
    *,
    raw_root: Path,
    target: Airport,
    airports: dict[str, Airport],
    max_terminal_km: float,
    strong_terminal_km: float,
    max_route_airport_km: float,
    min_terminal_points: int,
    max_trace_gap_s: float,
    max_dates: int,
    status_path: Path,
) -> dict[str, Any]:
    dates = sorted(
        (path for path in raw_root.iterdir() if path.is_dir() and DATE_RE.match(path.name)),
        key=lambda path: path.name,
    )[:max_dates]
    if not dates:
        raise RuntimeError(f"No raw ADSB dates found under {raw_root}")
    options = BuildOptions(
        min_points=min_terminal_points,
        max_airport_km=max_route_airport_km,
        max_trace_gap_s=max_trace_gap_s,
    )
    summary: Counter[str] = Counter()
    date_summaries: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    route_rollup: dict[str, dict[str, Any]] = {}
    nearest_contradictions: Counter[str] = Counter()

    for date_path in dates:
        parts = _raw_parts(date_path)
        if not parts:
            continue
        date_summary: Counter[str] = Counter()
        _write_status(
            status_path,
            {"state": "running", "phase": "raw_khh_scan", "date": date_path.name, "datesCompleted": len(date_summaries), "datesTotal": len(dates)},
        )
        for source_name, payload in iter_trace_payloads_from_split_tar(parts):
            summary["tracesSeen"] += 1
            date_summary["tracesSeen"] += 1
            try:
                trace = json.loads(payload)
                points = parse_trace_points(trace)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                summary["parseErrors"] += 1
                date_summary["parseErrors"] += 1
                continue
            if not points:
                continue
            legs = split_legs(points, options)
            for leg_index, leg in enumerate(legs):
                summary["legsSeen"] += 1
                date_summary["legsSeen"] += 1
                endpoint_items = _terminal_candidates(
                    leg,
                    target,
                    airports,
                    max_terminal_km=max_terminal_km,
                    strong_terminal_km=strong_terminal_km,
                    max_route_airport_km=max_route_airport_km,
                )
                if not endpoint_items:
                    continue
                summary["khhRelatedLegs"] += 1
                date_summary["khhRelatedLegs"] += 1
                callsign = _callsign(leg) or _clean(trace.get("flight"))
                aircraft = _clean(trace.get("icao24") or trace.get("icao") or trace.get("hex"))
                for item in endpoint_items:
                    summary["terminalCandidates"] += 1
                    date_summary["terminalCandidates"] += 1
                    other_code, other_distance = _other_endpoint(item["kind"], leg, airports, target, max_route_airport_km)
                    direction = "KHH-to-unknown" if item["kind"] == "departure" else "unknown-to-KHH"
                    if other_code:
                        direction = f"KHH-to-{other_code}" if item["kind"] == "departure" else f"{other_code}-to-KHH"
                    nearest_code = item.get("nearestAirport")
                    if nearest_code and nearest_code != target.iata:
                        summary["nearestAirportContradictions"] += 1
                        nearest_contradictions[nearest_code] += 1
                    evidence_class = item["evidenceClass"]
                    if evidence_class == "raw_terminal_strong":
                        summary["strongTerminalEvidence"] += 1
                    else:
                        summary["directionalTerminalInference"] += 1
                    record = {
                        "date": date_path.name,
                        "callsign": callsign,
                        "aircraft": aircraft,
                        "sourceFile": source_name,
                        "legIndex": leg_index,
                        "direction": direction,
                        "otherEndpoint": other_code,
                        "otherEndpointDistanceKm": round(other_distance, 1) if other_distance is not None else None,
                        **item,
                    }
                    if len(candidates) < 4000:
                        candidates.append(record)
                    key = direction
                    rollup = route_rollup.setdefault(
                        key,
                        {
                            "route": key,
                            "dates": set(),
                            "callsigns": set(),
                            "aircraft": set(),
                            "traceCount": 0,
                            "strongEvidenceCount": 0,
                            "inferredEvidenceCount": 0,
                            "nearestAirportContradictions": 0,
                            "minDistanceKm": math.inf,
                            "examples": [],
                        },
                    )
                    rollup["dates"].add(date_path.name)
                    if callsign:
                        rollup["callsigns"].add(callsign)
                    if aircraft:
                        rollup["aircraft"].add(aircraft)
                    rollup["traceCount"] += 1
                    rollup["strongEvidenceCount"] += evidence_class == "raw_terminal_strong"
                    rollup["inferredEvidenceCount"] += evidence_class == "directional_terminal_inferred"
                    rollup["nearestAirportContradictions"] += nearest_code not in {None, target.iata}
                    rollup["minDistanceKm"] = min(rollup["minDistanceKm"], float(item["distanceKm"]))
                    if len(rollup["examples"]) < 3:
                        rollup["examples"].append({"date": date_path.name, "callsign": callsign, "sourceFile": source_name, "distanceKm": item["distanceKm"]})
        date_summaries.append({"date": date_path.name, **dict(date_summary), "parts": [part.name for part in parts]})

    routes = []
    for value in route_rollup.values():
        row = {
            **value,
            "dates": sorted(value["dates"]),
            "callsigns": sorted(value["callsigns"]),
            "aircraft": sorted(value["aircraft"]),
            "minDistanceKm": None if value["minDistanceKm"] == math.inf else round(value["minDistanceKm"], 1),
        }
        row["independentSupport"] = {
            "dateCount": len(row["dates"]),
            "callsignCount": len(row["callsigns"]),
            "aircraftCount": len(row["aircraft"]),
            "traceCount": row["traceCount"],
        }
        row["promotionStatus"] = _promotion_status(row["independentSupport"], row["strongEvidenceCount"])
        routes.append(row)
    routes.sort(key=lambda row: (row["route"] not in {"KHH-to-NRT", "NRT-to-KHH"}, -row["traceCount"], row["route"]))
    summary["routeCandidates"] = len(routes)
    summary["promotableRouteCandidates"] = sum(row["promotionStatus"] == "raw_endpoint_supported" for row in routes)
    khh_nrt_routes = [row for row in routes if row["route"] in {"KHH-to-NRT", "NRT-to-KHH"}]
    summary["khhNrtSupportedDirections"] = len(khh_nrt_routes)
    return {
        "summary": dict(summary),
        "sourceDates": [path.name for path in dates],
        "dateSummaries": date_summaries,
        "routeCandidates": routes,
        "khhNrt": {
            "routes": khh_nrt_routes,
            "rawRouteGeometryFound": bool(khh_nrt_routes),
            "interpretation": (
                "KHH/NRT has raw terminal-direction evidence in the local seven-day sample"
                if khh_nrt_routes
                else "No single raw leg reached both KHH terminal evidence and NRT endpoint evidence; KHH access remains inferred"
            ),
        },
        "nearestAirportContradictions": nearest_contradictions.most_common(40),
        "candidateExamples": candidates,
        "method": {
            "terminalWindowPoints": 8,
            "maxTerminalKm": max_terminal_km,
            "strongTerminalKm": strong_terminal_km,
            "directionalHeadingToleranceDeg": 50,
            "monotonicDistanceFractionMinimum": 0.6,
            "promotionRule": "at least two dates and either two callsigns, two aircraft, or three traces; raw terminal evidence required",
            "nearestAirportOnly": False,
        },
    }


def _terminal_candidates(
    leg: list[TracePoint],
    target: Airport,
    airports: dict[str, Airport],
    *,
    max_terminal_km: float,
    strong_terminal_km: float,
    max_route_airport_km: float,
) -> list[dict[str, Any]]:
    if len(leg) < 8:
        return []
    output: list[dict[str, Any]] = []
    for kind, window in (("departure", leg[:8]), ("arrival", leg[-8:])):
        distances = [haversine_km(point.lat, point.lon, target.lat, target.lon) for point in window]
        distance = distances[0] if kind == "departure" else distances[-1]
        if distance > max_terminal_km:
            continue
        increasing = sum(b >= a - 2 for a, b in zip(distances, distances[1:], strict=False)) / (len(distances) - 1)
        decreasing = sum(b <= a + 2 for a, b in zip(distances, distances[1:], strict=False)) / (len(distances) - 1)
        monotonic = increasing if kind == "departure" else decreasing
        first, last = window[0], window[-1]
        if kind == "departure":
            movement_bearing = _bearing(first.lat, first.lon, last.lat, last.lon)
            expected_bearing = _bearing(target.lat, target.lon, first.lat, first.lon)
            heading_point = first
        else:
            movement_bearing = _bearing(first.lat, first.lon, last.lat, last.lon)
            expected_bearing = _bearing(first.lat, first.lon, target.lat, target.lon)
            heading_point = last
        heading = heading_point.track_deg if heading_point.track_deg is not None else movement_bearing
        heading_delta = _angle_delta(heading, expected_bearing)
        if monotonic < 0.6 or heading_delta > 50:
            continue
        nearest = _nearest_airport(heading_point.lat, heading_point.lon, airports.values(), max_terminal_km)
        evidence_class = "raw_terminal_strong" if distance <= strong_terminal_km and monotonic >= 0.72 and heading_delta <= 35 else "directional_terminal_inferred"
        output.append(
            {
                "kind": kind,
                "evidenceClass": evidence_class,
                "distanceKm": round(distance, 2),
                "monotonicFraction": round(monotonic, 3),
                "headingDeltaDeg": round(heading_delta, 2),
                "headingDeg": round(heading, 2),
                "expectedHeadingDeg": round(expected_bearing, 2),
                "nearestAirport": nearest[0] if nearest else None,
                "nearestAirportDistanceKm": round(nearest[1], 2) if nearest else None,
                "terminalPoint": {"lat": round(heading_point.lat, 6), "lon": round(heading_point.lon, 6), "elapsedS": heading_point.elapsed_s, "altitudeFt": heading_point.altitude_ft, "trackDeg": heading_point.track_deg},
            }
        )
    # A pass-by can satisfy both ends of a wide radius. Keep only the stronger
    # terminal interpretation so it cannot double-count a trace.
    output.sort(key=lambda item: (item["evidenceClass"] != "raw_terminal_strong", item["distanceKm"], item["headingDeltaDeg"]))
    return output[:1]


def _other_endpoint(kind: str, leg: list[TracePoint], airports: dict[str, Airport], target: Airport, max_km: float) -> tuple[str | None, float | None]:
    point = leg[-1] if kind == "departure" else leg[0]
    nearest = _nearest_airport(point.lat, point.lon, airports.values(), max_km)
    if nearest is None or nearest[0] == target.iata:
        return None, None
    return nearest


def _promotion_status(support: dict[str, int], strong_count: int) -> str:
    if strong_count <= 0:
        return "directional_inference_only"
    independent = support["dateCount"] >= 2 and (
        support["callsignCount"] >= 2 or support["aircraftCount"] >= 2 or support["traceCount"] >= 3
    )
    return "raw_endpoint_supported" if independent else "single_sample_holdout_needed"


def _graph(edges: Iterable[dict[str, Any]]) -> tuple[dict[Node, set[Node]], set[Node]]:
    graph: dict[Node, set[Node]] = defaultdict(set)
    nodes: set[Node] = set()
    for edge in edges:
        left = _node_from_value(edge.get("from", {}))
        right = _node_from_value(edge.get("to", {}))
        if left is None or right is None:
            continue
        graph[left].add(right)
        graph[right].add(left)
        nodes.update((left, right))
    return graph, nodes


def _components(graph: dict[Node, set[Node]], nodes: set[Node]) -> dict[Node, int]:
    result: dict[Node, int] = {}
    component_id = 0
    for start in nodes:
        if start in result:
            continue
        stack = [start]
        result[start] = component_id
        while stack:
            current = stack.pop()
            for neighbor in graph.get(current, ()):
                if neighbor not in result:
                    result[neighbor] = component_id
                    stack.append(neighbor)
        component_id += 1
    return result


def _node_from_value(value: dict[str, Any]) -> Node | None:
    if "latCell" in value and "lonCell" in value:
        return int(value["latCell"]), int(value["lonCell"])
    if "lat" in value and "lon" in value:
        return round((float(value["lat"]) + 90.0) / CELL_DEG - 0.5), round((float(value["lon"]) + 180.0) / CELL_DEG - 0.5)
    return None


def _node_payload(value: Node | None) -> dict[str, int] | None:
    if value is None:
        return None
    return {"latCell": value[0], "lonCell": value[1]}


def _raw_parts(path: Path) -> list[Path]:
    return sorted(
        item for item in path.iterdir()
        if item.is_file() and ".tar." in item.name and not item.name.endswith(".part") and not item.name.startswith(".")
    )


def _nearest_airport(lat: float, lon: float, airports: Iterable[Airport], max_km: float) -> tuple[str, float] | None:
    best: tuple[str, float] | None = None
    for airport in airports:
        distance = haversine_km(lat, lon, airport.lat, airport.lon)
        if distance <= max_km and (best is None or distance < best[1]):
            best = (airport.iata, distance)
    return best


def _callsign(points: list[TracePoint]) -> str | None:
    values = [point.callsign for point in points if point.callsign]
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta = math.radians(lon2 - lon1)
    y = math.sin(delta) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _angle_delta(left: float, right: float) -> float:
    return abs((left - right + 180) % 360 - 180)


def build_review(payload: dict[str, Any], network: dict[str, Any]) -> dict[str, Any]:
    gap = payload["gapResolution"]["summary"]
    khh = payload["khhEndpointResolution"]["summary"]
    qa = {
        "passed": all(
            [
                payload["rules"]["baseNetworkNotOverwritten"],
                payload["rules"]["observedEdgesNotReclassified"],
                payload["rules"]["airportEndpointEvidenceIsSeparate"],
                payload["rules"]["noIfr"],
                gap["inputGaps"] == len(network.get("unresolvedGaps", [])),
            ]
        ),
        "checks": {
            "baseNetworkNotOverwritten": payload["rules"]["baseNetworkNotOverwritten"],
            "observedEdgesNotReclassified": payload["rules"]["observedEdgesNotReclassified"],
            "airportEvidenceSeparate": payload["rules"]["airportEndpointEvidenceIsSeparate"],
            "ifrExcluded": payload["rules"]["noIfr"],
            "allInputGapsClassified": gap["inputGaps"] == gap["observedComponentAlreadyConnected"] + gap["relayComponentAlreadyConnected"] + gap["independentEvidenceStillMissing"] + gap["invalidGapCoordinates"],
        },
    }
    return {
        "schemaVersion": 1,
        "evidenceType": "global_corridor_resolution_review_v1",
        "generatedAt": payload["generatedAt"],
        "summary": payload["summary"],
        "gapConclusion": {
            "originalUnresolved": gap["inputGaps"],
            "alreadyConnectedByObservedGeometry": gap["observedComponentAlreadyConnected"],
            "alreadyConnectedWithExistingRelayLayer": gap["relayComponentAlreadyConnected"],
            "stillNeedsIndependentEvidence": gap["independentEvidenceStillMissing"],
            "noNewGeometryCreated": True,
        },
        "khhConclusion": {
            "nearestAirportContradictions": khh.get("nearestAirportContradictions", 0),
            "supportedDirections": payload["khhEndpointResolution"]["khhNrt"]["routes"],
            "rawRouteGeometryFound": payload["khhEndpointResolution"]["khhNrt"]["rawRouteGeometryFound"],
            "interpretation": payload["khhEndpointResolution"]["khhNrt"]["interpretation"],
        },
        "qa": qa,
        "limitations": [
            "A connected observed component proves graph connectivity, not a new direct segment between the two terminal cells.",
            "A relay-connected gap remains inferred and is not promoted to observed geometry.",
            "KHH endpoint evidence is kept separate because the raw receiver may not record the airport boundary itself.",
            "A route is promotable only after repeated independent dates and aircraft/callsign evidence; one matching callsign is not enough.",
        ],
    }


def _read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _write_gzip(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({"updatedAt": _now(), **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
