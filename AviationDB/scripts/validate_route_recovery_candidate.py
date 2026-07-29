#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_DIAGNOSTIC_DIR = PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "diagnostics"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate whether a corridor diagnostic can be promoted to recovered_endpoint.")
    parser.add_argument("--route", required=True, help="Route id, for example KHH-NRT.")
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--max-origin-km", type=float, default=220)
    parser.add_argument("--max-destination-km", type=float, default=120)
    parser.add_argument("--min-corridor-fraction", type=float, default=0.55)
    parser.add_argument("--min-progress", type=float, default=0.55)
    parser.add_argument("--reject-nearest-first", nargs="*", default=["TPE", "TSA", "RMQ", "OGN", "ISG"])
    args = parser.parse_args()

    diagnostic = json.loads(args.diagnostic.read_text(encoding="utf-8"))
    candidates = diagnostic.get("candidates", {}).get(args.route, [])
    report = validate_route_recovery(
        route=args.route,
        candidates=candidates,
        max_origin_km=args.max_origin_km,
        max_destination_km=args.max_destination_km,
        min_corridor_fraction=args.min_corridor_fraction,
        min_progress=args.min_progress,
        reject_nearest_first=set(args.reject_nearest_first),
    )
    output = args.output or DEFAULT_DIAGNOSTIC_DIR / f"{diagnostic.get('date', 'unknown')}-{args.route}-recovery-validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0


def validate_route_recovery(
    route: str,
    candidates: list[dict[str, Any]],
    max_origin_km: float,
    max_destination_km: float,
    min_corridor_fraction: float,
    min_progress: float,
    reject_nearest_first: set[str],
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    reject_counts: dict[str, int] = {}
    for candidate in candidates:
        reasons = rejection_reasons(
            candidate,
            max_origin_km=max_origin_km,
            max_destination_km=max_destination_km,
            min_corridor_fraction=min_corridor_fraction,
            min_progress=min_progress,
            reject_nearest_first=reject_nearest_first,
        )
        row = {
            "callsign": candidate.get("callsign"),
            "score": candidate.get("score"),
            "sourceFile": candidate.get("sourceFile"),
            "firstOriginKm": candidate.get("firstOriginKm"),
            "lastDestinationKm": candidate.get("lastDestinationKm"),
            "corridorFraction": candidate.get("corridorFraction"),
            "progress": candidate.get("progress"),
            "nearestFirst": candidate.get("nearestFirst"),
            "nearestLast": candidate.get("nearestLast"),
            "firstPoint": candidate.get("firstPoint"),
            "lastPoint": candidate.get("lastPoint"),
            "rejectionReasons": reasons,
        }
        if reasons:
            rejected.append(row)
            for reason in reasons:
                reject_counts[reason] = reject_counts.get(reason, 0) + 1
        else:
            accepted.append(row)

    accepted.sort(key=lambda item: item.get("score") or 0, reverse=True)
    rejected.sort(key=lambda item: item.get("score") or 0, reverse=True)
    can_promote = bool(accepted)
    return {
        "schemaVersion": 1,
        "route": route,
        "policy": {
            "maxOriginKm": max_origin_km,
            "maxDestinationKm": max_destination_km,
            "minCorridorFraction": min_corridor_fraction,
            "minProgress": min_progress,
            "rejectNearestFirst": sorted(reject_nearest_first),
        },
        "summary": {
            "candidates": len(candidates),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "canPromoteRecoveredEndpoint": can_promote,
            "topRejectReasons": sorted(reject_counts.items(), key=lambda item: item[1], reverse=True)[:20],
        },
        "acceptedCandidates": accepted[:20],
        "rejectedExamples": rejected[:40],
    }


def rejection_reasons(
    candidate: dict[str, Any],
    max_origin_km: float,
    max_destination_km: float,
    min_corridor_fraction: float,
    min_progress: float,
    reject_nearest_first: set[str],
) -> list[str]:
    reasons: list[str] = []
    first_origin_km = float(candidate.get("firstOriginKm") or 999999)
    last_destination_km = float(candidate.get("lastDestinationKm") or 999999)
    corridor_fraction = float(candidate.get("corridorFraction") or 0)
    progress = float(candidate.get("progress") or 0)
    nearest_first = (candidate.get("nearestFirst") or {}).get("iata")
    nearest_last = (candidate.get("nearestLast") or {}).get("iata")
    if first_origin_km > max_origin_km:
        reasons.append("first_point_too_far_from_origin")
    if last_destination_km > max_destination_km:
        reasons.append("last_point_too_far_from_destination")
    if corridor_fraction < min_corridor_fraction:
        reasons.append("corridor_fraction_too_low")
    if progress < min_progress:
        reasons.append("route_progress_too_low")
    if nearest_first in reject_nearest_first:
        reasons.append("competing_nearest_first_airport")
    if nearest_last not in {None, "NRT"}:
        reasons.append("destination_competes_with_non_target_airport")
    return reasons


if __name__ == "__main__":
    raise SystemExit(main())
