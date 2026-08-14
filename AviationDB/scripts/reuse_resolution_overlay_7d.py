#!/usr/bin/env python3
"""Rebind an existing raw KHH evidence scan to a new relay-only network.

When only the network assembly changes, rescanning millions of raw traces is
unnecessary.  This script reclassifies gaps against the new network and reuses
the already verified KHH terminal evidence from the prior overlay.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))

from resolve_global_gap_and_khh_endpoints_7d import (  # noqa: E402
    _read_gzip,
    _write_gzip,
    build_review,
    classify_gaps,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--prior-overlay", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()

    _status(args.status, {"state": "running", "phase": "load_reusable_raw_evidence"})
    network = _read_gzip(args.network)
    prior = _read_gzip(args.prior_overlay)
    prior_khh = prior.get("khhEndpointResolution")
    if not isinstance(prior_khh, dict) or not prior_khh.get("summary"):
        raise SystemExit("prior overlay has no reusable KHH evidence")

    _status(args.status, {"state": "running", "phase": "reclassify_gaps"})
    gap_result = classify_gaps(network)
    args.output_root.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).isoformat()
    summary = {
        "networkUnresolvedGaps": len(network.get("unresolvedGaps", [])),
        "gapResolution": gap_result["summary"],
        "khhEndpointResolution": prior_khh["summary"],
        "rawSourceDates": prior.get("summary", {}).get("rawSourceDates", []),
        "ifrExcluded": True,
        "rawInputsPreserved": True,
        "rawEvidenceReused": True,
        "observedGeometryUntouched": True,
    }
    payload = {
        "schemaVersion": 2,
        "evidenceType": "global_corridor_resolution_overlay_7d_reused_raw_evidence_v1",
        "generatedAt": generated_at,
        "source": {
            "network": str(args.network),
            "priorOverlay": str(args.prior_overlay),
            "rawEvidence": prior.get("source", {}).get("rawRoot"),
        },
        "summary": summary,
        "gapResolution": gap_result,
        "khhEndpointResolution": prior_khh,
        "rules": {
            "baseNetworkNotOverwritten": True,
            "observedEdgesNotReclassified": True,
            "airportEndpointEvidenceIsSeparate": True,
            "independentEvidenceRequiresRawTraceOrExistingObservedPath": True,
            "noIfr": True,
            "noAirportPairScheduleGeneration": True,
            "noLongStraightLineFill": True,
            "rawEvidenceReusedWithoutRescan": True,
        },
    }
    output = args.output_root / "global-corridor-resolution-overlay.json.gz"
    _write_gzip(output, payload)
    review = build_review(payload, network)
    review["limitations"].append("KHH raw evidence was reused from the prior immutable raw scan; no raw date was rescanned.")
    review["rawEvidenceReused"] = True
    (args.output_root / "global-corridor-resolution-review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _status(args.status, {"state": "complete", "phase": "written", "output": str(output), "summary": summary, "qa": review["qa"]})
    print(json.dumps({"state": "complete", "summary": summary, "qa": review["qa"]}, ensure_ascii=False, indent=2))
    return 0 if review["qa"]["passed"] else 2


def _status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({"updatedAt": datetime.now(UTC).isoformat(), **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
