#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from aviationdb.ifr_routing import DEFAULT_COST_CONFIG, DirectedAirgraph, select_ifr_route_shape_from_graph  # noqa: E402
from select_global_route_shapes import pair_source_from_route  # noqa: E402
from select_pair_route_shape import airport_lookup, no_adsb_support  # noqa: E402


DEFAULT_AIRPORT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "airports-index.json"
DEFAULT_AIRGRAPH = ROOT / "shared" / "offline-packs" / "aviation" / "regions" / "global.airgraph.json"
DEFAULT_OBSERVED = (
    PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "observed-routes.global.json.gz"
)
DEFAULT_OUTPUT_DIR = PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol"
DEFAULT_STATUS = Path("/private/tmp/travel-globe-observed-ifr-validation/status.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate observed ADS-B route geometry against directed IFR routing.")
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--airgraph", type=Path, default=DEFAULT_AIRGRAPH)
    parser.add_argument("--observed", type=Path, default=DEFAULT_OBSERVED)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--progress-every", type=int, default=250)
    parser.add_argument("--mean-threshold-km", type=float, default=120.0)
    parser.add_argument("--max-threshold-km", type=float, default=420.0)
    parser.add_argument("--review-mean-threshold-km", type=float, default=220.0)
    parser.add_argument("--review-max-threshold-km", type=float, default=800.0)
    parser.add_argument("--endpoint-threshold-km", type=float, default=650.0)
    parser.add_argument("--detour-threshold", type=float, default=2.2)
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help="Append to an existing rows JSONL and skip routes already written there.",
    )
    args = parser.parse_args()

    airports = airport_lookup(args.airport_index)
    airgraph_pack = json.loads(args.airgraph.read_text(encoding="utf-8"))
    cost_config = {**DEFAULT_COST_CONFIG}
    graph = DirectedAirgraph(airgraph_pack, cost_config)
    connector_cache: dict[tuple[str, str], list[Any]] = {}
    observed_pack = read_json(args.observed)
    routes = observed_pack.get("routes", [])
    if args.limit is not None:
        routes = routes[: args.limit]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.status.parent.mkdir(parents=True, exist_ok=True)
    rows_path = args.output_dir / "observed-routes-ifr-validation.jsonl"
    summary_path = args.output_dir / "observed-routes-ifr-validation-summary.json"
    report_path = args.output_dir / "observed-routes-ifr-validation.json.gz"

    counters: Counter[str] = Counter()
    processed = 0
    routes_with_observed_points = 0
    routes_without_observed_points = 0
    routes_with_ifr_comparison = 0
    if args.resume_existing and rows_path.exists():
        resume = summarize_rows_jsonl(rows_path)
        counters.update(resume["counters"])
        processed = min(int(resume["processed"]), len(routes))
        routes_with_observed_points = int(resume["routesWithObservedPoints"])
        routes_without_observed_points = int(resume["routesWithoutObservedPoints"])
        routes_with_ifr_comparison = int(resume["routesWithIfrComparison"])
    else:
        rows_path.unlink(missing_ok=True)
    write_status(args.status, "running", total=len(routes), processed=processed, counters=dict(counters), rows=str(rows_path))

    mode = "a" if processed else "w"
    with rows_path.open(mode, encoding="utf-8") as rows_handle:
        for index, route in enumerate(routes[processed:], processed + 1):
            row = validate_route(route, airports, graph, cost_config, connector_cache, args)
            counters[row["classification"]] += 1
            if row.get("hasObservedPoints"):
                routes_with_observed_points += 1
            else:
                routes_without_observed_points += 1
            if row.get("hasIfrComparison"):
                routes_with_ifr_comparison += 1
            rows_handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            if index % args.progress_every == 0:
                write_status(
                    args.status,
                    "running",
                    total=len(routes),
                    processed=index,
                    counters=dict(counters),
                    rows=str(rows_path),
                )

    summary = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "sourceObservedPack": str(args.observed),
        "policy": {
            "meanThresholdKm": args.mean_threshold_km,
            "maxThresholdKm": args.max_threshold_km,
            "reviewMeanThresholdKm": args.review_mean_threshold_km,
            "reviewMaxThresholdKm": args.review_max_threshold_km,
            "endpointThresholdKm": args.endpoint_threshold_km,
            "detourThreshold": args.detour_threshold,
        },
        "summary": {
            "routesValidated": processed_rows_count(rows_path),
            "classifications": dict(counters),
            "routesWithObservedPoints": routes_with_observed_points,
            "routesWithoutObservedPoints": routes_without_observed_points,
            "routesWithIfrComparison": routes_with_ifr_comparison,
        },
        "outputs": {
            "rowsJsonl": str(rows_path),
            "reportJsonGz": str(report_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_streaming_report(report_path, summary, rows_path)
    write_status(
        args.status,
        "complete",
        total=len(routes),
        processed=len(routes),
        counters=dict(counters),
        summary=str(summary_path),
        report=str(report_path),
        rows=str(rows_path),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def validate_route(
    route: dict[str, Any],
    airports: dict[str, dict[str, Any]],
    graph: DirectedAirgraph,
    cost_config: dict[str, float],
    connector_cache: dict[tuple[str, str], list[Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    route_id = route.get("id") or f"{route.get('originIata')}-{route.get('destinationIata')}"
    origin = airports.get(str(route.get("originIata") or "").upper())
    destination = airports.get(str(route.get("destinationIata") or "").upper())
    base = {
        "id": route_id,
        "originIata": route.get("originIata"),
        "destinationIata": route.get("destinationIata"),
        "sampleCount": route.get("sampleCount") or 0,
        "variantCount": route.get("variantCount") or 0,
        "shapePruned": bool(route.get("shapePruned")),
        "hasObservedPoints": False,
        "hasIfrComparison": False,
    }
    if not origin or not destination:
        return {**base, "classification": "observed_adsb_needs_review", "reason": "missing_airport_metadata"}

    representative = route.get("representative") if isinstance(route.get("representative"), dict) else {}
    raw_points = representative.get("points") if isinstance(representative, dict) else None
    if not raw_points:
        return {
            **base,
            "classification": "observed_adsb_no_observed_geometry",
            "reason": "representative_points_were_pruned_or_missing",
        }

    observed_points = to_points(raw_points)
    if len(observed_points) < 2:
        return {**base, "classification": "observed_adsb_needs_review", "reason": "too_few_observed_points"}

    base["hasObservedPoints"] = True
    observed_metrics = observed_only_metrics(observed_points, origin, destination)
    if observed_metrics["originGapKm"] > args.endpoint_threshold_km or observed_metrics["destinationGapKm"] > args.endpoint_threshold_km:
        return {
            **base,
            "classification": "observed_adsb_endpoint_suspect",
            "reason": "observed_trace_endpoint_too_far_from_airport",
            "metrics": observed_metrics,
        }
    if observed_metrics["observedDirectDetourRatio"] > args.detour_threshold:
        return {
            **base,
            "classification": "observed_adsb_excessive_detour",
            "reason": "observed_route_detour_ratio_exceeds_policy",
            "metrics": observed_metrics,
        }
    pair_source = pair_source_from_route(
        {
            "id": route_id,
            "originIata": route.get("originIata"),
            "destinationIata": route.get("destinationIata"),
            "bestSource": "observed_adsb",
            "routeScore": route.get("sampleCount") or 0,
            "sourceTypes": ["observed_adsb"],
            "openFlightsCount": 0,
            "aircraftTypes": [],
        }
    )
    departure = cached_connectors(connector_cache, graph, origin, mode="departure")
    arrival = cached_connectors(connector_cache, graph, destination, mode="arrival")
    result = select_ifr_route_shape_from_graph(
        graph,
        origin,
        destination,
        route_id=str(route_id),
        pair_source=pair_source,
        adsb_support=no_adsb_support(),
        k=10,
        config=cost_config,
        departure=departure,
        arrival=arrival,
    )
    if result.get("routeUnavailable"):
        return {
            **base,
            "classification": "observed_adsb_no_ifr_comparison",
            "reason": result.get("unavailableReason") or "ifr_route_unavailable",
            "connectorDiagnostics": result.get("connectorDiagnostics") or {},
        }

    selected = result.get("selected") or {}
    ifr_points = [
        {"lat": float(point["lat"]), "lon": float(point["lon"])}
        for point in selected.get("points", [])
        if isinstance(point, dict) and point.get("lat") is not None and point.get("lon") is not None
    ]
    if len(ifr_points) < 2:
        return {**base, "classification": "observed_adsb_no_ifr_comparison", "reason": "ifr_points_missing"}

    metrics = compare_observed_to_ifr(observed_points, ifr_points, origin, destination)
    classification, reason = classify_metrics(metrics, args)
    return {
        **base,
        "classification": classification,
        "reason": reason,
        "hasIfrComparison": True,
        "ifrMethod": selected.get("method"),
        "ifrScore": selected.get("score"),
        "metrics": metrics,
    }


def summarize_rows_jsonl(path: Path) -> dict[str, Any]:
    counters: Counter[str] = Counter()
    processed = 0
    routes_with_observed_points = 0
    routes_without_observed_points = 0
    routes_with_ifr_comparison = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                break
            processed += 1
            counters[str(row.get("classification") or "unknown")] += 1
            if row.get("hasObservedPoints"):
                routes_with_observed_points += 1
            else:
                routes_without_observed_points += 1
            if row.get("hasIfrComparison"):
                routes_with_ifr_comparison += 1
    return {
        "processed": processed,
        "counters": counters,
        "routesWithObservedPoints": routes_with_observed_points,
        "routesWithoutObservedPoints": routes_without_observed_points,
        "routesWithIfrComparison": routes_with_ifr_comparison,
    }


def cached_connectors(
    cache: dict[tuple[str, str], list[Any]],
    graph: DirectedAirgraph,
    airport: dict[str, Any],
    *,
    mode: str,
) -> list[Any]:
    airport_key = str(airport.get("iataCode") or airport.get("icaoCode") or airport.get("ident") or airport.get("iata") or "")
    if not airport_key:
        airport_key = f"{airport.get('latitude')},{airport.get('longitude')}"
    key = (airport_key, mode)
    if key not in cache:
        cache[key] = graph.connectors(airport, mode=mode)
    return cache[key]


def processed_rows_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def write_streaming_report(report_path: Path, summary: dict[str, Any], rows_path: Path) -> None:
    with gzip.open(report_path, "wt", encoding="utf-8", compresslevel=9) as handle:
        handle.write(json.dumps(summary, ensure_ascii=False, separators=(",", ":"))[:-1])
        handle.write(',"routes":[')
        first = True
        with rows_path.open(encoding="utf-8") as rows_handle:
            for line in rows_handle:
                clean = line.strip()
                if not clean:
                    continue
                if first:
                    first = False
                else:
                    handle.write(",")
                handle.write(clean)
        handle.write("]}\n")


def classify_metrics(metrics: dict[str, float], args: argparse.Namespace) -> tuple[str, str]:
    if metrics["originGapKm"] > args.endpoint_threshold_km or metrics["destinationGapKm"] > args.endpoint_threshold_km:
        return "observed_adsb_endpoint_suspect", "observed_trace_endpoint_too_far_from_airport"
    if metrics["observedDirectDetourRatio"] > args.detour_threshold:
        return "observed_adsb_excessive_detour", "observed_route_detour_ratio_exceeds_policy"
    if (
        metrics["meanObservedToIfrKm"] <= args.mean_threshold_km
        and metrics["maxObservedToIfrKm"] <= args.max_threshold_km
        and metrics["meanIfrToObservedKm"] <= args.mean_threshold_km
    ):
        return "observed_adsb_validated", "observed_shape_matches_directed_ifr_corridor"
    if (
        metrics["meanObservedToIfrKm"] <= args.review_mean_threshold_km
        and metrics["maxObservedToIfrKm"] <= args.review_max_threshold_km
    ):
        return "observed_adsb_needs_review", "observed_shape_near_ifr_corridor_but_outside_validated_threshold"
    return "observed_adsb_ifr_mismatch", "observed_shape_mismatches_directed_ifr_corridor"


def to_points(rows: list[Any]) -> list[dict[str, float]]:
    points = []
    for row in rows:
        if not isinstance(row, list | tuple) or len(row) < 2:
            continue
        try:
            points.append({"lat": float(row[0]), "lon": float(row[1])})
        except (TypeError, ValueError):
            continue
    return points


def compare_observed_to_ifr(
    observed: list[dict[str, float]],
    ifr: list[dict[str, float]],
    origin: dict[str, Any],
    destination: dict[str, Any],
) -> dict[str, float]:
    observed_to_ifr = [distance_to_polyline_km(point, ifr) for point in observed]
    ifr_to_observed = [distance_to_polyline_km(point, observed) for point in ifr]
    observed_distance = route_distance_km(observed)
    ifr_distance = route_distance_km(ifr)
    direct_distance = haversine_km(origin["latitude"], origin["longitude"], destination["latitude"], destination["longitude"])
    return {
        "meanObservedToIfrKm": round(sum(observed_to_ifr) / len(observed_to_ifr), 1),
        "maxObservedToIfrKm": round(max(observed_to_ifr), 1),
        "meanIfrToObservedKm": round(sum(ifr_to_observed) / len(ifr_to_observed), 1),
        "maxIfrToObservedKm": round(max(ifr_to_observed), 1),
        "observedDistanceKm": round(observed_distance, 1),
        "ifrDistanceKm": round(ifr_distance, 1),
        "directDistanceKm": round(direct_distance, 1),
        "observedIfrDistanceRatio": round(observed_distance / max(1.0, ifr_distance), 3),
        "observedDirectDetourRatio": round(observed_distance / max(1.0, direct_distance), 3),
        "originGapKm": round(haversine_km(origin["latitude"], origin["longitude"], observed[0]["lat"], observed[0]["lon"]), 1),
        "destinationGapKm": round(haversine_km(destination["latitude"], destination["longitude"], observed[-1]["lat"], observed[-1]["lon"]), 1),
    }


def observed_only_metrics(
    observed: list[dict[str, float]],
    origin: dict[str, Any],
    destination: dict[str, Any],
) -> dict[str, float]:
    observed_distance = route_distance_km(observed)
    direct_distance = haversine_km(origin["latitude"], origin["longitude"], destination["latitude"], destination["longitude"])
    return {
        "observedDistanceKm": round(observed_distance, 1),
        "directDistanceKm": round(direct_distance, 1),
        "observedDirectDetourRatio": round(observed_distance / max(1.0, direct_distance), 3),
        "originGapKm": round(haversine_km(origin["latitude"], origin["longitude"], observed[0]["lat"], observed[0]["lon"]), 1),
        "destinationGapKm": round(haversine_km(destination["latitude"], destination["longitude"], observed[-1]["lat"], observed[-1]["lon"]), 1),
    }


def distance_to_polyline_km(point: dict[str, float], line: list[dict[str, float]]) -> float:
    return min(distance_to_segment_km(point, line[index - 1], line[index]) for index in range(1, len(line)))


def distance_to_segment_km(point: dict[str, float], a: dict[str, float], b: dict[str, float]) -> float:
    mid_lat = math.radians((a["lat"] + b["lat"] + point["lat"]) / 3)
    bx = (b["lon"] - a["lon"]) * 111.320 * math.cos(mid_lat)
    by = (b["lat"] - a["lat"]) * 110.574
    px = (point["lon"] - a["lon"]) * 111.320 * math.cos(mid_lat)
    py = (point["lat"] - a["lat"]) * 110.574
    denom = bx * bx + by * by
    t = 0.0 if denom == 0 else max(0.0, min(1.0, (px * bx + py * by) / denom))
    return math.hypot(px - t * bx, py - t * by)


def route_distance_km(points: list[dict[str, float]]) -> float:
    return sum(
        haversine_km(points[index - 1]["lat"], points[index - 1]["lon"], points[index]["lat"], points[index]["lon"])
        for index in range(1, len(points))
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = rlat2 - rlat1
    dlon = math.radians(lon2 - lon1)
    value = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1, math.sqrt(value)))


def read_json(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def write_status(path: Path, state: str, **extra: Any) -> None:
    path.write_text(json.dumps({"state": state, "updatedAt": now_iso(), **extra}, ensure_ascii=False) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
