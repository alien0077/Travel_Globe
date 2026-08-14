#!/usr/bin/env python3
"""Download one fixed ADSB.lol release with bounded retry and atomic files."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from aviationdb.observed_routes import fetch_preferred_releases  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely download one fixed ADSB.lol raw release.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()

    _write_status(args.status, {"state": "resolving", "date": args.date})
    releases = fetch_preferred_releases(args.year)
    entry = releases.get(args.date)
    if entry is None:
        _write_status(args.status, {"state": "blocked", "date": args.date, "reason": "release_not_found"})
        raise SystemExit(f"No preferred release found for {args.date}")

    raw_dir = args.raw_root / args.date
    raw_dir.mkdir(parents=True, exist_ok=True)
    parts: list[dict[str, object]] = []
    for url in entry.urls:
        name = url.rstrip("/").split("/")[-1]
        target = raw_dir / name
        partial = target.with_name(f".{name}.part")
        if not target.exists() or target.stat().st_size == 0:
            _write_status(args.status, {"state": "downloading", "date": args.date, "asset": name})
            command = [
                "curl", "-fL", "--retry", "2", "--retry-delay", "5",
                "--retry-connrefused", "--connect-timeout", "30",
                "--max-time", "7200", "--continue-at", "-", "--output", str(partial), url,
            ]
            try:
                subprocess.run(command, check=True)
            except subprocess.CalledProcessError as error:
                _write_status(args.status, {"state": "blocked", "date": args.date, "asset": name, "reason": f"curl_exit_{error.returncode}"})
                raise
            if not partial.exists() or partial.stat().st_size == 0:
                _write_status(args.status, {"state": "blocked", "date": args.date, "asset": name, "reason": "empty_download"})
                raise SystemExit(f"Empty download for {url}")
            partial.replace(target)
        parts.append({"path": str(target), "bytes": target.stat().st_size, "url": url})
    payload = {"state": "complete", "date": args.date, "updatedAt": _now(), "releaseDir": str(raw_dir), "parts": parts, "totalBytes": sum(int(item["bytes"]) for item in parts)}
    _write_status(args.status, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_status(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updatedAt": _now(), **payload}
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
