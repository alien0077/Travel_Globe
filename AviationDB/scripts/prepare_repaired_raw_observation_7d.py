#!/usr/bin/env python3
"""Stage a repaired single day into an existing 7-day raw-derived set.

Only the repaired date is scanned from raw.  The other six immutable daily
outputs are hard-linked from the previously validated seven-day release, so
the downstream global merge still receives a complete seven-day input set
without rescanning unaffected tar archives.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATES = ["2026-08-02", "2026-08-01", "2026-07-31", "2026-07-30", "2026-07-29", "2026-07-28", "2026-07-27"]
CELL_DEG = 0.25


def main() -> int:
    parser = argparse.ArgumentParser(description="Reparse only one repaired raw date and stage the other six daily outputs.")
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--base-output-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repair-date", required=True, choices=DATES)
    parser.add_argument("--job-dir", type=Path, required=True)
    args = parser.parse_args()

    args.output_root.mkdir(parents=True, exist_ok=True)
    args.job_dir.mkdir(parents=True, exist_ok=True)
    staged: list[dict[str, object]] = []
    for date in DATES:
        destination = args.output_root / date / "raw-derived-corridor.json.gz"
        if date == args.repair_date:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if _valid_output(destination, date):
                source_kind = "repaired_daily_output_existing"
            else:
                source_kind = "repaired_raw_reparse"
                _process_repaired_date(args, destination)
            staged.append(_file_record(date, destination, source_kind))
            continue

        source = args.base_output_root / date / "raw-derived-corridor.json.gz"
        if not _valid_output(source, date):
            raise SystemExit(f"missing or invalid unaffected daily output: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            os.link(source, destination)
        elif not _valid_output(destination, date):
            raise SystemExit(f"existing staged output is invalid: {destination}")
        staged.append(_file_record(date, destination, "validated_daily_output_reused"))

    manifest = {
        "schemaVersion": 1,
        "evidenceType": "repaired_single_day_incremental_observation_manifest_v1",
        "repairDate": args.repair_date,
        "dates": staged,
        "baseOutputRoot": str(args.base_output_root),
        "rawRoot": str(args.raw_root),
        "generatedAt": _now(),
    }
    _atomic_json(args.job_dir / "incremental-observation-manifest.json", manifest)
    _atomic_json(args.job_dir / "incremental-observation.status.json", {"state": "complete", "repairDate": args.repair_date, "dates": staged, "updatedAt": _now()})
    print(json.dumps({"state": "complete", "repairDate": args.repair_date, "reparsedDates": [args.repair_date], "reusedDates": [date for date in DATES if date != args.repair_date]}, ensure_ascii=False))
    return 0


def _process_repaired_date(args: argparse.Namespace, destination: Path) -> None:
    raw_dir = args.raw_root / args.repair_date
    if not (raw_dir / "v2026.08.01-planes-readsb-prod-0.tar.aa").is_file() or not (raw_dir / "v2026.08.01-planes-readsb-prod-0.tar.ab").is_file():
        raise SystemExit(f"repaired raw release set is incomplete: {raw_dir}")
    command = [
        sys.executable,
        str(ROOT / "scripts/process_raw_corridor_day.py"),
        "--date", args.repair_date,
        "--raw-dir", str(raw_dir),
        "--output", str(destination),
        "--cell-deg", str(CELL_DEG),
        "--progress", str(args.job_dir / f"process-{args.repair_date}.progress.json"),
        "--checkpoint-dir", str(args.job_dir / f"checkpoints-{args.repair_date}"),
    ]
    subprocess.run(command, check=True)


def _valid_output(path: Path, date: str) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        return (
            payload.get("date") == date
            and isinstance(payload.get("corridorEdges"), list)
            and abs(float(payload.get("method", {}).get("cellDegrees", -1)) - CELL_DEG) < 1e-9
        )
    except (OSError, EOFError, json.JSONDecodeError):
        return False


def _file_record(date: str, path: Path, source_kind: str) -> dict[str, object]:
    return {"date": date, "path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path), "sourceKind": source_kind}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
