#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
DEFAULT_COMPLETION_DIR = (
    PROJECT
    / "data"
    / "releases"
    / "private"
    / "observed-routes"
    / "adsblol"
    / "daily-ifr-21d"
    / "post-ifr-completion"
)
DEFAULT_RUNTIME_PACK = ROOT / "shared" / "offline-packs" / "route-shapes" / "global.route-shapes.runtime.json"
DEFAULT_SHARED_DIR = ROOT / "shared" / "offline-packs" / "route-shapes"
DEFAULT_PUBLIC_DIR = ROOT / "replay-engine" / "public" / "offline-packs" / "route-shapes"

PROTECTED_METHODS = {"directed_airway_graph"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge accepted-with-review observed route shapes into route-shape selection overlays.")
    parser.add_argument("--completion-dir", type=Path, default=DEFAULT_COMPLETION_DIR)
    parser.add_argument("--runtime-pack", type=Path, default=DEFAULT_RUNTIME_PACK)
    parser.add_argument("--shared-dir", type=Path, default=DEFAULT_SHARED_DIR)
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    shape_dir = args.completion_dir / "shape-selections"
    accepted_rows = read_jsonl(args.completion_dir / "accepted-with-review.jsonl")
    runtime_routes = read_runtime_routes(args.runtime_pack)
    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "source": str(args.completion_dir),
        "acceptedRows": len(accepted_rows),
        "merged": [],
        "skipped": [],
    }
    for row in accepted_rows:
        pair = str(row.get("airportPair") or "")
        selection_path = shape_dir / f"{pair}.shape-selection.json"
        if not pair or not selection_path.exists():
            report["skipped"].append({"airportPair": pair, "reason": "missing_shape_selection"})
            continue
        existing = runtime_routes.get(pair)
        existing_method = existing.get("m") if isinstance(existing, dict) else None
        if existing_method in PROTECTED_METHODS:
            report["skipped"].append(
                {
                    "airportPair": pair,
                    "reason": "protected_existing_runtime_route",
                    "existingMethod": existing_method,
                }
            )
            continue
        for target_dir in [args.shared_dir, args.public_dir]:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(selection_path, target_dir / selection_path.name)
        report["merged"].append(
            {
                "airportPair": pair,
                "method": "observed_adsb_mapped",
                "shared": str(args.shared_dir / selection_path.name),
                "public": str(args.public_dir / selection_path.name),
            }
        )
    report_path = args.report or args.completion_dir / "accepted-review-merge-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "merged": len(report["merged"]),
                "skipped": len(report["skipped"]),
                "report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_runtime_routes(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    routes = payload.get("routes")
    return routes if isinstance(routes, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
