#!/usr/bin/env python3
"""Run the compact long-leg extractor once per retained raw date.

The manifest is the only source of scheduling truth.  Completed dates are
validated and skipped; incomplete dates resume from the extractor checkpoint.
No download, deletion, or runtime-pack mutation occurs here.
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
DATES = ["2026-08-02", "2026-08-01", "2026-07-31", "2026-07-30", "2026-07-29", "2026-07-28", "2026-07-27"]
DEFAULT_JOB_DIR = Path("/private/tmp/travel-globe-long-legs-7d")
DEFAULT_RAW_ROOT = PROJECT / "data/raw/adsblol"
DEFAULT_AIRPORT_INDEX = PROJECT.parent / "shared/offline-packs/core-global/airports-index.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run retained seven-day long raw leg extraction with resume manifest.")
    parser.add_argument("--job-dir", type=Path, default=DEFAULT_JOB_DIR)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    args = parser.parse_args()
    # The extractor runs from AviationDB/, while callers normally pass paths
    # relative to the monorepo root.  Normalize them before constructing the
    # per-date command so a resumed run cannot silently look in AviationDB/
    # AviationDB/data/... .
    args.job_dir = args.job_dir.expanduser().resolve()
    args.raw_root = args.raw_root.expanduser().resolve()
    args.airport_index = args.airport_index.expanduser().resolve()
    args.job_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.job_dir / "manifest.json"
    manifest = _load_manifest(manifest_path)
    _write_status(args.job_dir / "status.json", {"state": "running", "phase": "long_leg_extraction"})

    failures: list[dict[str, Any]] = []
    for date in DATES:
        output = args.job_dir / date / "raw-long-legs.json.gz"
        raw_dir = args.raw_root / date
        if _valid_output(output, date):
            manifest["dates"][date] = {
                "state": "complete",
                "output": str(output),
                "updatedAt": _now(),
                "reason": "existing_valid_output",
            }
            _write_manifest(manifest_path, manifest)
            continue
        if not raw_dir.exists():
            failure = {"date": date, "state": "blocked", "reason": "missing_raw_dir"}
            manifest["dates"][date] = failure
            failures.append(failure)
            _write_manifest(manifest_path, manifest)
            continue

        date_dir = args.job_dir / date
        date_dir.mkdir(parents=True, exist_ok=True)
        log_path = date_dir / "extract.log"
        manifest["dates"][date] = {"state": "running", "startedAt": _now(), "output": str(output)}
        _write_manifest(manifest_path, manifest)
        command = [
            sys.executable,
            str(PROJECT / "scripts/extract_long_raw_legs.py"),
            "--date",
            date,
            "--raw-dir",
            str(raw_dir),
            "--output",
            str(output),
            "--airport-index",
            str(args.airport_index),
            "--checkpoint-dir",
            str(date_dir / "checkpoints"),
            "--progress",
            str(date_dir / "progress.json"),
        ]
        started = time.monotonic()
        with log_path.open("a", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT, check=False)
        if result.returncode != 0 or not _valid_output(output, date):
            failure = {
                "date": date,
                "state": "blocked",
                "returnCode": result.returncode,
                "reason": "extractor_failed_or_output_invalid",
                "log": str(log_path),
                "wallSeconds": round(time.monotonic() - started, 3),
            }
            manifest["dates"][date] = failure
            failures.append(failure)
            _write_manifest(manifest_path, manifest)
            continue
        manifest["dates"][date] = {
            "state": "complete",
            "output": str(output),
            "updatedAt": _now(),
            "wallSeconds": round(time.monotonic() - started, 3),
        }
        _write_manifest(manifest_path, manifest)

    complete = sum(value.get("state") == "complete" for value in manifest["dates"].values())
    state = "complete" if complete == len(DATES) else "blocked" if failures else "running"
    _write_status(
        args.job_dir / "status.json",
        {
            "state": state,
            "phase": "long_leg_extraction",
            "completeDates": complete,
            "totalDates": len(DATES),
            "failures": failures,
        },
    )
    print(
        json.dumps(
            {"state": state, "completeDates": complete, "totalDates": len(DATES), "failures": failures},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if state == "complete" else 2


def _load_manifest(path: Path) -> dict[str, Any]:
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("datesOrder") == DATES and isinstance(value.get("dates"), dict):
            return value
    return {"schemaVersion": 1, "pipelineVersion": "long-raw-legs-7d-v1", "datesOrder": DATES, "dates": {}}


def _valid_output(path: Path, date: str) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            value = json.load(handle)
        return value.get("evidenceType") == "raw_derived_long_leg_geometry" and value.get("date") == date
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    payload["updatedAt"] = _now()
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({**payload, "updatedAt": _now()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
