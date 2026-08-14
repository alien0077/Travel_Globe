#!/usr/bin/env python3
"""Redownload, validate, and atomically repair one ADSB.lol split-tar part."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from aviationdb.observed_routes import ConcatenatedBinaryIO  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair one corrupt ADSB.lol raw split part safely.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--part-name", required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    raw_dir = args.raw_dir
    target = raw_dir / args.part_name
    temp = raw_dir / f".{args.part_name}.repair.part"
    backup = raw_dir / f"{args.part_name}.corrupt-backup-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    preceding = sorted(
        path for path in raw_dir.iterdir()
        if path.is_file() and path.name.endswith((".tar.aa", ".tar.ab", ".tar.ac", ".tar.ad", ".tar.ae", ".tar.af")) and path.name != args.part_name
    )
    if not preceding:
        raise SystemExit(f"No preceding split tar part found in {raw_dir}")
    _status(args.status, {"state": "downloading", "date": args.date, "part": args.part_name, "url": args.url})
    temp.unlink(missing_ok=True)
    subprocess.run([
        "curl", "-fL", "--retry", "3", "--retry-delay", "5", "--retry-connrefused",
        "--connect-timeout", "30", "--max-time", "7200", "--output", str(temp), args.url,
    ], check=True)
    if not temp.is_file() or temp.stat().st_size == 0:
        raise SystemExit("redownload produced an empty part")
    _status(args.status, {"state": "validating", "date": args.date, "part": args.part_name, "bytes": temp.stat().st_size})
    validation = _validate_split_tar([*preceding, temp])
    if validation["badTraceMembers"] or validation["tarError"]:
        temp.unlink(missing_ok=True)
        _status(args.status, {"state": "blocked", "date": args.date, "part": args.part_name, "reason": "validation_failed", "validation": validation})
        raise SystemExit(f"repaired raw validation failed: {validation}")
    old_sha = _sha256(target) if target.exists() else None
    new_sha = _sha256(temp)
    if target.exists():
        shutil.copy2(target, backup)
    os.replace(temp, target)
    manifest = {
        "schemaVersion": 1,
        "evidenceType": "adsblol_raw_repair_manifest_v1",
        "date": args.date,
        "part": args.part_name,
        "url": args.url,
        "oldPath": str(backup) if backup.exists() else None,
        "oldSha256": old_sha,
        "newSha256": new_sha,
        "newBytes": target.stat().st_size,
        "validation": validation,
        "rawPreserved": backup.exists(),
        "completedAt": _now(),
    }
    manifest_path = raw_dir / f"raw-repair-{args.date}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _status(args.status, {"state": "complete", "date": args.date, "part": args.part_name, "manifest": str(manifest_path), "validation": validation})
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def _validate_split_tar(parts: list[Path]) -> dict[str, object]:
    trace_members = 0
    bad_members = 0
    bad_examples: list[str] = []
    tar_error: str | None = None
    try:
        with ConcatenatedBinaryIO(parts) as raw:
            with tarfile.open(fileobj=raw, mode="r|*") as archive:
                for member in archive:
                    if not member.isfile() or "/traces/" not in member.name or not member.name.endswith(".json"):
                        continue
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        continue
                    trace_members += 1
                    payload = extracted.read()
                    try:
                        if payload.startswith(b"\x1f\x8b"):
                            gzip.decompress(payload)
                        else:
                            json.loads(payload)
                    except (EOFError, OSError, ValueError, json.JSONDecodeError):
                        bad_members += 1
                        if len(bad_examples) < 10:
                            bad_examples.append(member.name)
    except (OSError, EOFError, tarfile.TarError, ValueError) as error:
        tar_error = repr(error)
    return {"traceMembers": trace_members, "badTraceMembers": bad_members, "badExamples": bad_examples, "tarError": tar_error}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _status(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps({"updatedAt": _now(), **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
