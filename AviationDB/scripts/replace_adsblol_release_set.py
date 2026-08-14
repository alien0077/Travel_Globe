#!/usr/bin/env python3
"""Replace a corrupt ADSB.lol release with a validated complete release set.

Used only when the preferred release itself contains corrupt trace payloads.
The old part metadata is retained; the old corrupt `.ab` is retained as a
backup, while the old `.aa` may be released only after its checksum is written
because the disk quota cannot hold two 2 GB split parts.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import zlib
from datetime import UTC, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from aviationdb.observed_routes import ConcatenatedBinaryIO  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace a corrupt ADSB.lol release set safely.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--old-prefix", required=True)
    parser.add_argument("--new-prefix", required=True)
    parser.add_argument("--release-url", required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()

    raw_dir = args.raw_dir
    old_parts = [raw_dir / f"{args.old_prefix}.tar.aa", raw_dir / f"{args.old_prefix}.tar.ab"]
    new_parts = [raw_dir / f"{args.new_prefix}.tar.aa", raw_dir / f"{args.new_prefix}.tar.ab"]
    temp_parts = [raw_dir / f".{path.name}.replacement.part" for path in new_parts]
    old_metadata = [{"path": str(path), "exists": path.exists(), "bytes": path.stat().st_size if path.exists() else 0, "sha256": _sha256(path) if path.exists() else None} for path in old_parts]
    # Keep an interrupted replacement part so a later versioned worker can
    # resume it with curl --continue-at -. Deleting it wastes bandwidth.
    # Failed repair leftovers are retained for provenance and are never used
    # as release inputs.
    urls = [f"{args.release_url}/{path.name}" for path in new_parts]
    _status(args.status, {"state": "downloading", "date": args.date, "sourceRelease": args.new_prefix, "urls": urls})
    for url, temp in zip(urls, temp_parts, strict=True):
        subprocess.run([
            "curl", "-fL", "--continue-at", "-", "--retry", "5", "--retry-all-errors",
            "--retry-delay", "5", "--retry-connrefused",
            "--connect-timeout", "30", "--max-time", "7200", "--output", str(temp), url,
        ], check=True)
        if not temp.is_file() or temp.stat().st_size == 0:
            raise SystemExit(f"empty replacement download: {url}")
    _status(args.status, {"state": "validating", "date": args.date, "sourceRelease": args.new_prefix, "bytes": [path.stat().st_size for path in temp_parts]})
    validation = _validate_split_tar(temp_parts)
    if validation["badTraceMembers"] or validation["tarError"]:
        for path in temp_parts:
            path.unlink(missing_ok=True)
        _status(args.status, {"state": "blocked", "date": args.date, "reason": "replacement_validation_failed", "validation": validation})
        raise SystemExit(f"replacement validation failed: {validation}")

    completed = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    # The old .ab is retained. The old 2 GB .aa is released only after its
    # checksum/provenance is durable in the manifest because quota is tight.
    old_ab_backup = raw_dir / f".{old_parts[1].name}.source-corrupt-backup-{completed}"
    if old_parts[1].exists():
        os.replace(old_parts[1], old_ab_backup)
    if old_parts[0].exists():
        old_parts[0].unlink()
    for old_part in old_parts:
        if old_part.exists():
            old_part.unlink()
    os.replace(temp_parts[0], new_parts[0])
    os.replace(temp_parts[1], new_parts[1])
    manifest = {
        "schemaVersion": 1,
        "evidenceType": "adsblol_raw_release_replacement_manifest_v1",
        "date": args.date,
        "oldRelease": args.old_prefix,
        "newRelease": args.new_prefix,
        "releaseUrl": args.release_url,
        "oldParts": old_metadata,
        "oldCorruptAbBackup": str(old_ab_backup) if old_ab_backup.exists() else None,
        "newParts": [{"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)} for path in new_parts],
        "validation": validation,
        "quotaConstrainedAaReplacement": True,
        "completedAt": _now(),
    }
    manifest_path = raw_dir / f"raw-repair-{args.date}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _status(args.status, {"state": "complete", "date": args.date, "manifest": str(manifest_path), "validation": validation})
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
                    except (EOFError, OSError, ValueError, json.JSONDecodeError, zlib.error):
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
