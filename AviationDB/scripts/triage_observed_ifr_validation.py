#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_INPUT_DIR = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "releases"
    / "private"
    / "observed-routes"
    / "adsblol"
    / "daily-ifr-21d"
)
DEFAULT_OUTPUT_DIR = DEFAULT_INPUT_DIR / "post-ifr-triage"
DEFAULT_STATUS = Path("/private/tmp/travel-globe-observed-ifr-triage/status.json")

TARGET_CLASSES = {
    "observed_adsb_needs_review",
    "observed_adsb_no_ifr_comparison",
    "observed_adsb_ifr_mismatch",
    "observed_adsb_excessive_detour",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Triage non-validated observed ADS-B routes after IFR validation.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--progress-every", type=int, default=5000)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.status.parent.mkdir(parents=True, exist_ok=True)
    write_status(args.status, "running", phase="scan-validation-rows")

    validation_files = sorted(args.input_dir.glob("*/ifr-validation-dedup/observed-routes-ifr-validation.jsonl"))
    if not validation_files:
        raise SystemExit(f"No validation JSONL files found under {args.input_dir}")

    counters: Counter[str] = Counter()
    queue_counters: Counter[str] = Counter()
    reason_counters: Counter[str] = Counter()
    rows_seen = 0
    rows_by_pair: dict[str, dict[str, Any]] = {}
    duplicates_by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)

    queue_paths = {
        "needs_review_promotable": args.output_dir / "needs-review-promotable.jsonl",
        "needs_review_manual": args.output_dir / "needs-review-manual.jsonl",
        "ifr_graph_gap_queue": args.output_dir / "ifr-graph-gap-queue.jsonl",
        "ifr_graph_suspect": args.output_dir / "ifr-graph-suspect.jsonl",
        "endpoint_or_trace_suspect": args.output_dir / "endpoint-or-trace-suspect.jsonl",
        "trace_quality_rejects": args.output_dir / "trace-quality-rejects.jsonl",
    }
    handles = {name: path.open("w", encoding="utf-8") for name, path in queue_paths.items()}
    try:
        for validation_file in validation_files:
            date = validation_file.parts[-3]
            with validation_file.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    rows_seen += 1
                    row = json.loads(line)
                    classification = str(row.get("classification") or "")
                    if classification not in TARGET_CLASSES:
                        continue
                    counters[classification] += 1
                    reason_counters[str(row.get("reason") or "unknown")] += 1
                    triaged = triage_row(row, date)
                    queue_name = triaged["triageQueue"]
                    queue_counters[queue_name] += 1
                    pair = triaged["airportPair"]
                    if pair in rows_by_pair:
                        duplicates_by_pair[pair].append(triaged)
                    else:
                        rows_by_pair[pair] = triaged
                    handles[queue_name].write(json.dumps(triaged, ensure_ascii=False, separators=(",", ":")) + "\n")
                    if rows_seen % args.progress_every == 0:
                        write_status(
                            args.status,
                            "running",
                            phase="scan-validation-rows",
                            rowsSeen=rows_seen,
                            counters=dict(counters),
                            queues=dict(queue_counters),
                        )
    finally:
        for handle in handles.values():
            handle.close()

    summary = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "inputDir": str(args.input_dir),
        "validationFiles": len(validation_files),
        "rowsSeen": rows_seen,
        "targetClassRows": sum(counters.values()),
        "targetClassCounts": dict(counters),
        "triageQueueCounts": dict(queue_counters),
        "reasonCounts": dict(reason_counters),
        "uniqueAirportPairs": len(rows_by_pair),
        "duplicateAirportPairs": {pair: len(rows) + 1 for pair, rows in sorted(duplicates_by_pair.items())},
        "policy": {
            "needsReviewPromotable": {
                "sampleCountMin": 3,
                "variantCountMax": 3,
                "observedDirectDetourRatioMax": 1.35,
                "endpointGapKmMax": 180,
                "meanObservedToIfrKmMax": 160,
                "maxObservedToIfrKmMax": 600,
                "meanIfrToObservedKmMax": 170,
            },
            "graphGapHighValue": {
                "sampleCountMin": 2,
                "observedDirectDetourRatioMax": 1.45,
                "endpointGapKmMax": 180,
            },
            "mismatchGraphSuspect": {
                "sampleCountMin": 2,
                "observedDirectDetourRatioMax": 1.6,
                "endpointGapKmMax": 220,
            },
        },
        "outputs": {name: str(path) for name, path in queue_paths.items()},
    }
    summary_path = args.output_dir / "triage-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_status(
        args.status,
        "complete",
        phase="complete",
        rowsSeen=rows_seen,
        counters=dict(counters),
        queues=dict(queue_counters),
        summary=str(summary_path),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def triage_row(row: dict[str, Any], date: str) -> dict[str, Any]:
    origin = str(row.get("originIata") or "").upper()
    destination = str(row.get("destinationIata") or "").upper()
    pair = f"{origin}-{destination}"
    classification = str(row.get("classification") or "")
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    sample_count = int(row.get("sampleCount") or 0)
    variant_count = int(row.get("variantCount") or 0)
    endpoint_gap = max(metric(metrics, "originGapKm"), metric(metrics, "destinationGapKm"))
    detour = metric(metrics, "observedDirectDetourRatio", default=999.0)
    mean_observed_to_ifr = metric(metrics, "meanObservedToIfrKm", default=9999.0)
    max_observed_to_ifr = metric(metrics, "maxObservedToIfrKm", default=9999.0)
    mean_ifr_to_observed = metric(metrics, "meanIfrToObservedKm", default=9999.0)

    queue = "needs_review_manual"
    action = "manual_review"
    priority = "normal"
    notes: list[str] = []

    if classification == "observed_adsb_needs_review":
        if (
            sample_count >= 3
            and variant_count <= 3
            and detour <= 1.35
            and endpoint_gap <= 180
            and mean_observed_to_ifr <= 160
            and max_observed_to_ifr <= 600
            and mean_ifr_to_observed <= 170
        ):
            queue = "needs_review_promotable"
            action = "promote_candidate_with_review_flag"
            priority = "high" if sample_count >= 8 and detour <= 1.2 else "normal"
            notes.append("near_ifr_corridor_with_stable_observed_support")
        else:
            notes.append("outside_auto_promote_policy")
    elif classification == "observed_adsb_no_ifr_comparison":
        queue = "ifr_graph_gap_queue"
        action = "repair_ifr_graph_or_connector_then_revalidate"
        priority = "high" if sample_count >= 2 and detour <= 1.45 and endpoint_gap <= 180 else "normal"
        notes.append("observed_pair_exists_but_directed_ifr_route_unavailable")
    elif classification == "observed_adsb_ifr_mismatch":
        if endpoint_gap > 220 or bool(row.get("shapePruned")) or variant_count > 6:
            queue = "endpoint_or_trace_suspect"
            action = "inspect_endpoint_trace_split_or_pruning"
            notes.append("endpoint_or_trace_quality_more_likely_than_graph")
        elif sample_count >= 2 and detour <= 1.6:
            queue = "ifr_graph_suspect"
            action = "inspect_ifr_candidate_selection_or_missing_corridor"
            priority = "high" if sample_count >= 5 else "normal"
            notes.append("observed_shape_plausible_but_ifr_corridor_far")
        else:
            queue = "endpoint_or_trace_suspect"
            action = "inspect_observed_shape_before_using"
            notes.append("low_support_or_high_detour_mismatch")
    elif classification == "observed_adsb_excessive_detour":
        if sample_count >= 2 and endpoint_gap <= 180:
            queue = "endpoint_or_trace_suspect"
            action = "try_trace_split_or_exception_review"
            notes.append("detour_excessive_but_endpoint_and_support_not_trivial")
        else:
            queue = "trace_quality_rejects"
            action = "exclude_from_formal_pack"
            priority = "low"
            notes.append("detour_exceeds_policy")

    return {
        "schemaVersion": 1,
        "date": date,
        "airportPair": pair,
        "originIata": origin,
        "destinationIata": destination,
        "classification": classification,
        "reason": row.get("reason"),
        "triageQueue": queue,
        "recommendedAction": action,
        "priority": priority,
        "sampleCount": sample_count,
        "variantCount": variant_count,
        "shapePruned": bool(row.get("shapePruned")),
        "hasIfrComparison": bool(row.get("hasIfrComparison")),
        "metrics": metrics,
        "notes": notes,
    }


def metric(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(metrics.get(key, default))
    except (TypeError, ValueError):
        return default


def write_status(path: Path, state: str, **values: Any) -> None:
    payload = {"state": state, "updatedAt": now_iso(), **values}
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
