#!/usr/bin/env python3
"""Stage 0.25-degree cross-continent daily evidence for one repaired date."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

DATES = ["2026-08-02", "2026-08-01", "2026-07-31", "2026-07-30", "2026-07-29", "2026-07-28", "2026-07-27"]
CELL_DEG = 0.25


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repair-date", required=True, choices=DATES)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    _atomic_json(args.output_root / ".resolution-0.25.json", {"cellDegrees": CELL_DEG, "source": str(args.base_root), "repairDate": args.repair_date, "updatedAt": datetime.now(UTC).isoformat()})
    records = []
    for date in DATES:
        source = args.base_root / f"{date}.json.gz"
        destination = args.output_root / source.name
        if date == args.repair_date:
            # Leave the repaired date absent so the extractor must scan its
            # repaired raw archive instead of accidentally reusing old data.
            destination.unlink(missing_ok=True)
            continue
        if not _valid(source, date):
            raise SystemExit(f"invalid base 0.25-degree cross-continent output: {source}")
        if destination.exists() and not _valid(destination, date):
            raise SystemExit(f"invalid staged cross-continent output: {destination}")
        if not destination.exists():
            os.link(source, destination)
        records.append({"date": date, "path": str(destination), "bytes": destination.stat().st_size, "sha256": _sha256(destination), "sourceKind": "validated_daily_cross_output_reused"})
    payload = {"state": "complete", "repairDate": args.repair_date, "cellDegrees": CELL_DEG, "reusedDates": records, "updatedAt": datetime.now(UTC).isoformat()}
    _atomic_json(args.status, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _valid(path: Path, date: str) -> bool:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        declared = payload.get("method", {}).get("cellDegrees", payload.get("cellDegrees"))
        return payload.get("date") == date and payload.get("evidenceType") == "raw_derived_global_cross_continent_flights_v1" and (declared is None or abs(float(declared) - CELL_DEG) < 1e-9)
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
