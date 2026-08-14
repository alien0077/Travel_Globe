#!/usr/bin/env python3
"""Resumable 7-day raw corridor producer/consumer orchestrator."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
DATES = ["2026-08-02", "2026-08-01", "2026-07-31", "2026-07-30", "2026-07-29", "2026-07-28", "2026-07-27"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed 7-day raw corridor pipeline in the background worker.")
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, default=PROJECT / "data/raw/adsblol")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "data/releases/private/observed-routes/adsblol/corridor-7d")
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Only process retained complete raw dates; never start a download worker.",
    )
    args = parser.parse_args()
    args.job_dir.mkdir(parents=True, exist_ok=True)
    args.output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = args.job_dir / "manifest.json"
    manifest = _load_or_create_manifest(manifest_path, args)
    _write_status(args.job_dir, {"state": "running", "phase": "preflight", "date": None})
    _quota_preflight(manifest, args)

    download_thread: threading.Thread | None = None
    download_result: dict[str, object] = {}
    for index, date in enumerate(DATES):
        # Preserve processed/processing states across a restart.  Rewriting a
        # completed date as raw_complete would force a needless full tar scan
        # and was the reason resume appeared to start from the first date.
        current_state = _date_state(manifest, date)
        if current_state not in {"processed", "qa_pass", "graph_ready", "processing"}:
            _update_date(manifest, date, "raw_complete" if _raw_complete(args.raw_root / date) else "planned")
        _write_manifest(manifest_path, manifest)
        next_date = DATES[index + 1] if index + 1 < len(DATES) else None
        if (
            not args.no_download
            and next_date
            and not _raw_complete(args.raw_root / next_date)
            and _date_state(manifest, next_date) not in {"raw_complete", "processed", "qa_pass", "graph_ready"}
        ):
            download_result = {}
            download_thread = threading.Thread(target=_download_one, args=(next_date, args, download_result), daemon=True)
            _update_date(manifest, next_date, "downloading")
            _write_manifest(manifest_path, manifest)
            download_thread.start()

        current_state = _date_state(manifest, date)
        existing_output = Path(str(manifest.get("dates", {}).get(date, {}).get("output", "")))
        if current_state == "processing" and _valid_daily_output(existing_output, date):
            _update_date(manifest, date, "processed", output=str(existing_output), outputBytes=existing_output.stat().st_size)
            _write_manifest(manifest_path, manifest)
        if _date_state(manifest, date) not in {"processed", "qa_pass", "graph_ready"}:
            result = _process_one(date, args, manifest, manifest_path)
            if date == DATES[0]:
                _write_benchmark(args.job_dir, date, result)
                _write_status(args.job_dir, {"state": "running", "phase": "benchmark_gate", "date": date, "benchmark": result})
                if not result or int(result.get("tracesSeen", 0)) <= 0:
                    _update_date(manifest, date, "blocked", reason="benchmark_missing_metrics")
                    _write_manifest(manifest_path, manifest)
                    return 3

        if download_thread is not None:
            download_thread.join()
            download_thread = None
            if download_result.get("error"):
                _update_date(manifest, next_date or date, "blocked", reason=str(download_result["error"]))
                _write_manifest(manifest_path, manifest)
                _write_status(args.job_dir, {"state": "blocked", "phase": "download", "date": next_date, "reason": str(download_result["error"])})
                return 2
            if next_date:
                _update_date(manifest, next_date, "raw_complete")
                _write_manifest(manifest_path, manifest)

    _write_status(args.job_dir, {"state": "complete", "phase": "all_dates_processed", "dates": DATES})
    return 0


def _download_one(date: str, args: argparse.Namespace, result: dict[str, object]) -> None:
    status = args.job_dir / f"download-{date}.status.json"
    command = [sys.executable, str(PROJECT / "scripts/download_raw_release_safe.py"), "--year", "2026", "--date", date, "--raw-root", str(args.raw_root), "--status", str(status)]
    try:
        subprocess.run(command, check=True)
    except Exception as error:  # noqa: BLE001
        result["error"] = repr(error)


def _process_one(date: str, args: argparse.Namespace, manifest: dict[str, object], manifest_path: Path) -> dict[str, object]:
    raw_dir = args.raw_root / date
    output = args.output_root / date / "raw-derived-corridor.json.gz"
    status_path = args.job_dir / f"process-{date}.status.json"
    _update_date(manifest, date, "processing", output=str(output))
    _write_manifest(manifest_path, manifest)
    _write_status(args.job_dir, {"state": "running", "phase": "processing", "date": date})
    progress = args.job_dir / f"process-{date}.progress.json"
    checkpoints = args.job_dir / f"checkpoints-{date}"
    command = [sys.executable, str(PROJECT / "scripts/process_raw_corridor_day.py"), "--date", date, "--raw-dir", str(raw_dir), "--output", str(output), "--progress", str(progress), "--checkpoint-dir", str(checkpoints)]
    started = time.monotonic()
    with status_path.open("w", encoding="utf-8") as log:
        try:
            completed = subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as error:
            _update_date(manifest, date, "blocked", reason=f"processor_exit_{error.returncode}")
            _write_manifest(manifest_path, manifest)
            _write_status(args.job_dir, {"state": "blocked", "phase": "processing", "date": date, "reason": f"processor_exit_{error.returncode}"})
            raise
    result = _read_last_json_line(status_path)
    result.setdefault("wallSeconds", round(time.monotonic() - started, 3))
    _update_date(manifest, date, "processed", output=str(output), wallSeconds=result["wallSeconds"], outputBytes=output.stat().st_size, metrics=result)
    _write_manifest(manifest_path, manifest)
    _write_status(args.job_dir, {"state": "running", "phase": "processed", "date": date, "outputBytes": output.stat().st_size})
    return result


def _read_last_json_line(path: Path) -> dict[str, object]:
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("stats"), dict):
            return dict(value["stats"])
    return {}


def _write_benchmark(job_dir: Path, date: str, metrics: dict[str, object]) -> None:
    traces = int(metrics.get("tracesSeen", 0))
    wall = float(metrics.get("wallSeconds", 0) or 0)
    payload = {"date": date, "tracesSeen": traces, "legsSeen": int(metrics.get("legsSeen", 0)), "wallSeconds": wall, "tracesPerSecond": round(traces / wall, 3) if wall > 0 else 0}
    path = job_dir / "benchmark.json"
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _quota_preflight(manifest: dict[str, object], args: argparse.Namespace) -> None:
    usage = shutil.disk_usage(args.raw_root)
    planned_bytes = int(manifest.get("plannedRawBytes", 0))
    existing_bytes = sum(_directory_bytes(args.raw_root / date) for date in DATES)
    missing_bytes = max(0, planned_bytes - existing_bytes)
    largest_day = max((int(item.get("estimatedBytes", 0)) for item in manifest.get("dates", {}).values()), default=0)
    # When all raw dates are already retained, only processing scratch space is
    # needed.  The previous estimate incorrectly reserved another full release
    # and could block a safe reparse despite no download being planned.
    processing_scratch = max(1_000_000_000, int(largest_day * 0.35))
    required = missing_bytes + processing_scratch
    manifest["quota"] = {"freeBytes": usage.free, "plannedRawBytes": planned_bytes, "existingRawBytes": existing_bytes, "requiredBytes": required, "passed": usage.free >= required}
    if usage.free < required:
        _write_manifest(Path(manifest["manifestPath"]), manifest)
        _write_status(args.job_dir, {"state": "blocked_quota", "phase": "preflight", "freeBytes": usage.free, "requiredBytes": required})
        raise SystemExit(f"quota preflight failed: free={usage.free} required={required}")
    _write_manifest(Path(manifest["manifestPath"]), manifest)


def _load_or_create_manifest(path: Path, args: argparse.Namespace) -> dict[str, object]:
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("datesOrder") != DATES:
            raise SystemExit("manifest date order differs; refusing to restart with a different scope")
        return manifest
    dates = {date: {"state": "raw_complete" if _raw_complete(args.raw_root / date) else "planned"} for date in DATES}
    existing = _directory_bytes(args.raw_root / "2026-08-02")
    estimate = max(existing, 3_300_000_000)
    manifest = {"schemaVersion": 1, "pipelineVersion": "raw-corridor-7d-v1", "evidenceType": "raw_derived_unbiased", "datesOrder": DATES, "dates": dates, "plannedRawBytes": estimate * len(DATES), "manifestPath": str(path), "createdAt": _now()}
    _write_manifest(path, manifest)
    return manifest


def _raw_complete(path: Path) -> bool:
    if not path.is_dir() or any(path.glob(".*.part")):
        return False
    parts = sorted(item for item in path.iterdir() if item.is_file() and ".tar." in item.name and not item.name.endswith(".headers"))
    return bool(parts) and all(item.stat().st_size > 0 for item in parts)


def _directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _valid_daily_output(path: Path, date: str) -> bool:
    """Accept a prior atomic output after an interruption following its write."""
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, EOFError, ValueError, json.JSONDecodeError):
        return False
    stats = payload.get("stats", {}) if isinstance(payload, dict) else {}
    return (
        isinstance(payload, dict)
        and payload.get("date") == date
        and payload.get("evidenceType") == "raw_derived_unbiased"
        and isinstance(payload.get("corridorEdges"), list)
        and int(stats.get("parseErrors", 1)) == 0
    )


def _date_state(manifest: dict[str, object], date: str) -> str:
    return str(manifest.get("dates", {}).get(date, {}).get("state", "planned"))


def _update_date(manifest: dict[str, object], date: str, state: str, **extra: object) -> None:
    row = manifest.setdefault("dates", {}).setdefault(date, {})
    row.update({"state": state, "updatedAt": _now(), **extra})


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _write_status(job_dir: Path, payload: dict[str, object]) -> None:
    path = job_dir / "status.json"
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({"updatedAt": _now(), **payload}, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
