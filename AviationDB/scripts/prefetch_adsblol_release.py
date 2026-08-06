#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from aviationdb.observed_routes import fetch_preferred_releases  # noqa: E402
from build_observed_routes_range import _download_with_curl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Prefetch one ADSB.lol preferred release into the raw download cache.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--status", type=Path)
    args = parser.parse_args()

    releases = fetch_preferred_releases(args.year)
    entry = releases.get(args.date)
    if entry is None:
        raise SystemExit(f"No ADSB.lol preferred release found for {args.date}.")

    release_dir = args.work_dir / args.date
    release_dir.mkdir(parents=True, exist_ok=True)
    write_status(args.status, "running", date=args.date, urls=entry.urls)
    parts = [_download_with_curl(url, release_dir) for url in entry.urls]
    payload = {
        "state": "complete",
        "updatedAt": now_iso(),
        "date": args.date,
        "releaseDir": str(release_dir),
        "parts": [{"path": str(path), "bytes": path.stat().st_size} for path in parts],
        "totalBytes": sum(path.stat().st_size for path in parts),
    }
    if args.status:
        args.status.parent.mkdir(parents=True, exist_ok=True)
        args.status.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def write_status(path: Path | None, state: str, **extra: object) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"state": state, "updatedAt": now_iso(), **extra}, ensure_ascii=False) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
