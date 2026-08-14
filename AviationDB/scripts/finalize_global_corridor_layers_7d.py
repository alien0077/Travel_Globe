#!/usr/bin/env python3
"""Finalize the seven-day global corridor evidence layers.

The output is a reviewable/runtime-ready pack with explicit observed, relay,
airport-access, and unresolved-gap layers.  It does not promote inferred
geometry to observed geometry and does not generate airport-pair schedules.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize global corridor evidence layers.")
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--raw-validation", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    _status(args.status, {"state": "running", "phase": "load"})

    network = _read_gzip(args.network)
    audit = _read_gzip(args.audit)
    raw_validation = json.loads(args.raw_validation.read_text(encoding="utf-8"))
    generated_at = datetime.now(UTC).isoformat()
    gaps = list(network.get("unresolvedGaps", []))
    gap_summary = _gap_summary(gaps)
    airport_access = audit.get("airportAccess", [])
    runtime_pack = {
        "schemaVersion": 1,
        "evidenceType": "global_corridor_runtime_layers_7d_v1",
        "generatedAt": generated_at,
        "source": {
            "network": str(args.network),
            "connectivityAudit": str(args.audit),
            "rawValidation": str(args.raw_validation),
        },
        "summary": {
            **network.get("summary", {}),
            "airportAccessLinks": sum(len(item.get("links", [])) for item in airport_access),
            "unresolvedGapCount": len(gaps),
            "rawObservedRelayPathFound": raw_validation.get("khhToNrt", {}).get("observedOnlyPathFound", False),
            "inferredRelayPathFound": raw_validation.get("khhToNrt", {}).get("pathFound", False),
            "airportAccessRelayPathFound": audit.get("khhToNrt", {}).get("pathFoundWithAirportAccess", False),
        },
        "layers": {
            "observedEdges": network.get("observedEdges", []),
            "relayInferred": network.get("relayInferred", []),
            "airportAccess": airport_access,
            "unresolvedGaps": gaps,
        },
        "validation": {
            "rawObservedRelay": raw_validation.get("khhToNrt", {}),
            "airportAccess": audit.get("khhToNrt", {}),
        },
        "gapSummary": gap_summary,
        "rules": {
            "observedLayerIsImmutable": True,
            "relayLayerIsInferredOnly": True,
            "airportAccessLayerIsInferredOnly": True,
            "unresolvedGapsExcludedFromObservedLayer": True,
            "noAirportPairScheduleGeneration": True,
            "noLongStraightLineFill": True,
            "ifrExcluded": True,
        },
    }
    _write_gzip(args.output_root / "global-corridor-runtime-layers.json.gz", runtime_pack)
    review = {
        "schemaVersion": 1,
        "evidenceType": "global_corridor_remaining_tasks_review_v1",
        "generatedAt": generated_at,
        "summary": runtime_pack["summary"],
        "gapSummary": gap_summary,
        "validation": runtime_pack["validation"],
        "qa": {
            "passed": bool(
                network.get("summary", {}).get("observedGeometryUntouched") is True
                and network.get("summary", {}).get("inferredGeometryNotObserved") is True
                and audit.get("qa", {}).get("passed") is True
                and raw_validation.get("khhToNrt", {}).get("observedOnlyPathFound") is False
                and audit.get("khhToNrt", {}).get("pathFoundWithAirportAccess") is True
            ),
            "checks": {
                "observedGeometryUntouched": network.get("summary", {}).get("observedGeometryUntouched") is True,
                "inferredSeparated": network.get("summary", {}).get("inferredGeometryNotObserved") is True,
                "connectivityAuditPassed": audit.get("qa", {}).get("passed") is True,
                "rawOnlyPathRemainsUnproven": raw_validation.get("khhToNrt", {}).get("observedOnlyPathFound") is False,
                "inferredRelayPathPresent": raw_validation.get("khhToNrt", {}).get("pathFound") is True,
                "airportAccessOnlyIsExplicit": raw_validation.get("khhToNrt", {}).get("pathFound") is False and audit.get("khhToNrt", {}).get("pathFoundWithAirportAccess") is True,
                "airportAccessPathExplicit": audit.get("khhToNrt", {}).get("pathFoundWithAirportAccess") is True,
            },
        },
        "remainingWork": [
            "Use independent holdout dates or route-specific traces to promote unresolved gaps.",
            "Validate individual long-haul route shapes such as CI8 separately from the shared corridor layer.",
            "KHH to NRT remains airport-access-only until independent middle geometry is recovered.",
        ],
    }
    (args.output_root / "global-corridor-remaining-tasks-review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _status(args.status, {"state": "complete", "phase": "written", "summary": runtime_pack["summary"], "qa": review["qa"]})
    print(json.dumps({"state": "complete", "summary": runtime_pack["summary"], "qa": review["qa"]}, ensure_ascii=False, indent=2))
    return 0 if review["qa"]["passed"] else 2


def _gap_summary(gaps: list[dict[str, Any]]) -> dict[str, Any]:
    status = Counter(str(item.get("status", "unknown")) for item in gaps)
    regions = Counter()
    distance_buckets = Counter()
    for item in gaps:
        pairs = {
            f"{left}:{right}"
            for left in item.get("sourceRegions", [])
            for right in item.get("targetRegions", [])
            if left != right
        }
        for pair in pairs:
            regions[pair] += 1
        distance = float(item.get("distanceKm", 0.0) or 0.0)
        bucket = "0-150km" if distance <= 150 else "150-350km" if distance <= 350 else ">350km"
        distance_buckets[bucket] += 1
    return {
        "count": len(gaps),
        "byStatus": dict(sorted(status.items())),
        "byCrossRegionPair": dict(sorted(regions.items())),
        "byDistance": dict(sorted(distance_buckets.items())),
        "policy": "Unresolved gaps remain review-only and are excluded from observed runtime geometry.",
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


def _status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({"updatedAt": datetime.now(UTC).isoformat(), **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
