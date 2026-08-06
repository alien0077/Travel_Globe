#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
DEFAULT_DAILY_DIR = PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "daily-ifr-21d"
DEFAULT_TRIAGE_DIR = DEFAULT_DAILY_DIR / "post-ifr-triage"
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "post-ifr-completion"
DEFAULT_AIRPORT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "airports-index.json"
DEFAULT_STATUS = Path("/private/tmp/travel-globe-observed-ifr-completion/status.json")


QUEUE_FILES = {
    "needs_review_promotable": "needs-review-promotable.jsonl",
    "needs_review_manual": "needs-review-manual.jsonl",
    "ifr_graph_gap_queue": "ifr-graph-gap-queue.jsonl",
    "ifr_graph_suspect": "ifr-graph-suspect.jsonl",
    "endpoint_or_trace_suspect": "endpoint-or-trace-suspect.jsonl",
    "trace_quality_rejects": "trace-quality-rejects.jsonl",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Complete post-IFR triage queues into route-shape overlays and action manifests.")
    parser.add_argument("--daily-dir", type=Path, default=DEFAULT_DAILY_DIR)
    parser.add_argument("--triage-dir", type=Path, default=DEFAULT_TRIAGE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--progress-every", type=int, default=1000)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.status.parent.mkdir(parents=True, exist_ok=True)
    write_status(args.status, "running", phase="load-inputs")

    airports = airport_lookup(args.airport_index)
    queues = {name: read_jsonl(args.triage_dir / filename) for name, filename in QUEUE_FILES.items()}
    counters = {name: len(rows) for name, rows in queues.items()}

    shape_dir = args.output_dir / "shape-selections"
    shape_dir.mkdir(parents=True, exist_ok=True)
    accepted_rows = process_promotable(queues["needs_review_promotable"], args.daily_dir, airports, shape_dir, args.status)
    manual_rows = rank_manual_review(queues["needs_review_manual"])
    graph_gap_rows = rank_graph_gaps(queues["ifr_graph_gap_queue"])
    graph_suspect_rows = rank_graph_suspects(queues["ifr_graph_suspect"])
    endpoint_rows = rank_endpoint_or_trace(queues["endpoint_or_trace_suspect"])
    reject_rows = rank_rejects(queues["trace_quality_rejects"])

    write_jsonl(args.output_dir / "accepted-with-review.jsonl", accepted_rows)
    write_jsonl(args.output_dir / "needs-review-manual-ranked.jsonl", manual_rows)
    write_jsonl(args.output_dir / "ifr-graph-gap-ranked.jsonl", graph_gap_rows)
    write_jsonl(args.output_dir / "ifr-graph-suspect-ranked.jsonl", graph_suspect_rows)
    write_jsonl(args.output_dir / "endpoint-or-trace-suspect-ranked.jsonl", endpoint_rows)
    write_jsonl(args.output_dir / "trace-quality-rejects-final.jsonl", reject_rows)

    manifests = {
        "acceptedWithReview": manifest_for_rows(accepted_rows, "accepted_with_review_flag"),
        "needsReviewManual": manifest_for_rows(manual_rows, "manual_review_required"),
        "ifrGraphGap": manifest_for_rows(graph_gap_rows, "repair_ifr_graph_or_connector"),
        "ifrGraphSuspect": manifest_for_rows(graph_suspect_rows, "inspect_ifr_selector"),
        "endpointOrTraceSuspect": manifest_for_rows(endpoint_rows, "inspect_endpoint_or_trace_split"),
        "traceQualityRejects": manifest_for_rows(reject_rows, "exclude_from_formal_pack"),
    }
    summary = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "dailyDir": str(args.daily_dir),
        "triageDir": str(args.triage_dir),
        "outputDir": str(args.output_dir),
        "inputs": counters,
        "summary": {
            "acceptedWithReview": len(accepted_rows),
            "acceptedShapeSelections": sum(1 for row in accepted_rows if row.get("shapeSelection")),
            "needsReviewManual": len(manual_rows),
            "ifrGraphGap": len(graph_gap_rows),
            "ifrGraphSuspect": len(graph_suspect_rows),
            "endpointOrTraceSuspect": len(endpoint_rows),
            "traceQualityRejects": len(reject_rows),
        },
        "manifests": manifests,
        "outputs": {
            "shapeSelections": str(shape_dir),
            "acceptedWithReview": str(args.output_dir / "accepted-with-review.jsonl"),
            "needsReviewManualRanked": str(args.output_dir / "needs-review-manual-ranked.jsonl"),
            "ifrGraphGapRanked": str(args.output_dir / "ifr-graph-gap-ranked.jsonl"),
            "ifrGraphSuspectRanked": str(args.output_dir / "ifr-graph-suspect-ranked.jsonl"),
            "endpointOrTraceSuspectRanked": str(args.output_dir / "endpoint-or-trace-suspect-ranked.jsonl"),
            "traceQualityRejectsFinal": str(args.output_dir / "trace-quality-rejects-final.jsonl"),
        },
    }
    (args.output_dir / "completion-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_status(args.status, "complete", phase="complete", summary=str(args.output_dir / "completion-summary.json"), **summary["summary"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def process_promotable(
    rows: list[dict[str, Any]],
    daily_dir: Path,
    airports: dict[str, dict[str, Any]],
    shape_dir: Path,
    status: Path,
) -> list[dict[str, Any]]:
    accepted = []
    observed_cache: dict[str, dict[str, dict[str, Any]]] = {}
    for index, row in enumerate(rows, 1):
        date = str(row.get("date") or "")
        pair = str(row.get("airportPair") or "")
        observed = observed_route_for_pair(date, pair, daily_dir, observed_cache)
        selection = build_observed_shape_selection(row, observed, airports)
        output_path = None
        if selection:
            output_path = shape_dir / f"{pair}.shape-selection.json"
            output_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        accepted.append(
            {
                **row,
                "completionAction": "accepted_with_review_flag" if selection else "accepted_without_shape_selection",
                "shapeSelection": str(output_path) if output_path else None,
                "representativeSourceDate": date,
                "requiresRuntimeMerge": bool(selection),
            }
        )
        if index % 100 == 0:
            write_status(status, "running", phase="promote-needs-review", processed=index, total=len(rows))
    return accepted


def build_observed_shape_selection(
    row: dict[str, Any],
    observed: dict[str, Any] | None,
    airports: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    pair = str(row.get("airportPair") or "")
    origin_iata = str(row.get("originIata") or "").upper()
    destination_iata = str(row.get("destinationIata") or "").upper()
    origin = airports.get(origin_iata)
    destination = airports.get(destination_iata)
    representative = observed.get("representative") if isinstance(observed, dict) else None
    raw_points = representative.get("points") if isinstance(representative, dict) else None
    observed_points = to_points(raw_points)
    if not origin or not destination or len(observed_points) < 2:
        return None
    points = [airport_point(origin, origin_iata)]
    points.extend(observed_point(point, index) for index, point in enumerate(observed_points, 1))
    points.append(airport_point(destination, destination_iata))
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    distance_km = metric(metrics, "observedDistanceKm", route_distance_km(points))
    return {
        "schemaVersion": 2,
        "generatedAt": now_iso(),
        "route": pair,
        "routeUnavailable": False,
        "selected": {
            "method": "observed_adsb_mapped",
            "score": review_score(row),
            "reason": "Observed ADS-B route promoted from needs_review by post-IFR triage policy.",
            "provenance": {
                "source": "adsblol-observed-ifr-triage",
                "warning": "Accepted with review flag: observed ADS-B shape was near the directed IFR corridor but did not fully meet validated thresholds.",
                "validationClassification": row.get("classification"),
                "validationReason": row.get("reason"),
                "sampleCount": row.get("sampleCount"),
                "variantCount": row.get("variantCount"),
                "date": row.get("date"),
            },
            "metrics": {
                "distanceKm": round(distance_km, 1),
                "detourRatio": metric(metrics, "observedDirectDetourRatio"),
                "meanObservedToIfrKm": metric(metrics, "meanObservedToIfrKm"),
                "maxObservedToIfrKm": metric(metrics, "maxObservedToIfrKm"),
                "meanIfrToObservedKm": metric(metrics, "meanIfrToObservedKm"),
            },
            "points": points,
        },
    }


def rank_manual_review(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (with_priority(row, "manual_review_required", manual_review_score(row)) for row in rows),
        key=lambda row: (-row["priorityScore"], row["airportPair"]),
    )


def rank_graph_gaps(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (with_priority(row, "repair_ifr_graph_or_connector", graph_gap_score(row)) for row in rows),
        key=lambda row: (-row["priorityScore"], row["airportPair"]),
    )


def rank_graph_suspects(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (with_priority(row, "inspect_ifr_selector_or_missing_corridor", graph_suspect_score(row)) for row in rows),
        key=lambda row: (-row["priorityScore"], row["airportPair"]),
    )


def rank_endpoint_or_trace(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (with_priority(row, "inspect_endpoint_recovery_trace_split_or_pair", endpoint_score(row)) for row in rows),
        key=lambda row: (-row["priorityScore"], row["airportPair"]),
    )


def rank_rejects(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (with_priority(row, "exclude_from_formal_pack_keep_evidence", reject_score(row)) for row in rows),
        key=lambda row: (-row["priorityScore"], row["airportPair"]),
    )


def with_priority(row: dict[str, Any], action: str, score: float) -> dict[str, Any]:
    return {
        **row,
        "completionAction": action,
        "priorityScore": round(score, 2),
        "priorityBand": "high" if score >= 70 else "normal" if score >= 35 else "low",
    }


def manual_review_score(row: dict[str, Any]) -> float:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    return (
        metric(row, "sampleCount") * 3
        + max(0.0, 1.5 - metric(metrics, "observedDirectDetourRatio", 9.0)) * 20
        + max(0.0, 250.0 - max(metric(metrics, "originGapKm"), metric(metrics, "destinationGapKm"))) / 5
        + max(0.0, 240.0 - metric(metrics, "meanObservedToIfrKm", 9999.0)) / 4
    )


def graph_gap_score(row: dict[str, Any]) -> float:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    return (
        metric(row, "sampleCount") * 5
        + max(0.0, 1.6 - metric(metrics, "observedDirectDetourRatio", 9.0)) * 25
        + max(0.0, 220.0 - max(metric(metrics, "originGapKm"), metric(metrics, "destinationGapKm"))) / 4
    )


def graph_suspect_score(row: dict[str, Any]) -> float:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    return metric(row, "sampleCount") * 5 + max(0.0, 1.7 - metric(metrics, "observedDirectDetourRatio", 9.0)) * 25


def endpoint_score(row: dict[str, Any]) -> float:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    return metric(row, "sampleCount") * 4 + max(metric(metrics, "originGapKm"), metric(metrics, "destinationGapKm")) / 10


def reject_score(row: dict[str, Any]) -> float:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    return metric(metrics, "observedDirectDetourRatio", 0.0) * 10 + metric(row, "sampleCount")


def observed_route_for_pair(
    date: str,
    pair: str,
    daily_dir: Path,
    cache: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any] | None:
    if date not in cache:
        path = daily_dir / date / f"observed-routes.{date}.dedup.json.gz"
        cache[date] = {}
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            cache[date] = {route.get("id") or f"{route.get('originIata')}-{route.get('destinationIata')}": route for route in payload.get("routes", [])}
    return cache[date].get(pair.lower()) or cache[date].get(pair.upper()) or cache[date].get(pair)


def airport_lookup(path: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for airport in json.loads(path.read_text(encoding="utf-8")).get("airports", []):
        iata = airport.get("iataCode")
        if iata:
            result[str(iata).upper()] = airport
    return result


def airport_point(airport: dict[str, Any], ident: str) -> dict[str, Any]:
    return {
        "ident": ident,
        "lat": safe_float(airport.get("latitude")),
        "lon": safe_float(airport.get("longitude")),
        "pointType": "AIRPORT",
    }


def observed_point(point: dict[str, float], index: int) -> dict[str, Any]:
    return {
        "ident": f"OBS{index:03d}",
        "lat": round(float(point["lat"]), 6),
        "lon": round(float(point["lon"]), 6),
        "pointType": "OBSERVED_ADSB",
    }


def to_points(rows: Any) -> list[dict[str, float]]:
    points = []
    if not isinstance(rows, list):
        return points
    for row in rows:
        if not isinstance(row, list | tuple) or len(row) < 2:
            continue
        try:
            points.append({"lat": float(row[0]), "lon": float(row[1])})
        except (TypeError, ValueError):
            continue
    return points


def route_distance_km(points: list[dict[str, Any]]) -> float:
    total = 0.0
    for index in range(1, len(points)):
        total += haversine_km(points[index - 1]["lat"], points[index - 1]["lon"], points[index]["lat"], points[index]["lon"])
    return total


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = rlat2 - rlat1
    dlon = math.radians(lon2 - lon1)
    value = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1, math.sqrt(value)))


def review_score(row: dict[str, Any]) -> float:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    return round(1000 + manual_review_score(row) - metric(metrics, "meanObservedToIfrKm", 9999.0), 2)


def manifest_for_rows(rows: list[dict[str, Any]], action: str) -> dict[str, Any]:
    priorities = Counter(row.get("priorityBand") for row in rows)
    by_origin_region = Counter((row.get("originIata") or "??")[:1] for row in rows)
    return {
        "action": action,
        "count": len(rows),
        "priorityBands": dict(priorities),
        "originInitials": dict(sorted(by_origin_region.items())),
        "topPairs": [row.get("airportPair") for row in rows[:20]],
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def metric(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(number, 6)


def write_status(path: Path, state: str, **values: Any) -> None:
    path.write_text(json.dumps({"state": state, "updatedAt": now_iso(), **values}, ensure_ascii=False) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
