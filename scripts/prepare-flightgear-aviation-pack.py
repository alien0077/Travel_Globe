#!/usr/bin/env python3
"""Prepare the public FlightGear-only aviation airgraph pack."""

from __future__ import annotations

import gzip
import io
import json
import os
import shutil
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SHARED_AVIATION_DIR = ROOT / "shared" / "offline-packs" / "aviation"
PUBLIC_AVIATION_DIR = ROOT / "replay-engine" / "public" / "offline-packs" / "aviation"
REGION_DIR = SHARED_AVIATION_DIR / "regions"
REGION_JSON = REGION_DIR / "global.airgraph.json"
REGION_GZIP = REGION_DIR / "global.airgraph.json.gz"
NOTICE_SOURCE = ROOT / "FLIGHTGEAR_LICENSE.txt"
GPL_SOURCE = ROOT / "LICENSES" / "GPL-2.0.txt"

NOTICE_RELATIVE = "FLIGHTGEAR_LICENSE.txt"
GPL_RELATIVE = "licenses/GPL-2.0.txt"
OBSOLETE_FILES = (
    "regions/asia-east.airgraph.json",
    "regions/asia-east.airgraph.json.gz",
)


def main() -> int:
    if not REGION_JSON.exists():
        raise SystemExit(f"Missing FlightGear airgraph source: {REGION_JSON}")
    if not NOTICE_SOURCE.exists():
        raise SystemExit(f"Missing FlightGear notice: {NOTICE_SOURCE}")
    if not GPL_SOURCE.exists():
        raise SystemExit(f"Missing GPL v2 text: {GPL_SOURCE}")

    raw = REGION_JSON.read_bytes()
    if not raw.endswith(b"\n"):
        raw += b"\n"
        REGION_JSON.write_bytes(raw)
    payload = json.loads(raw)
    _validate_flightgear_payload(payload)

    gz = _gzip_bytes(raw)
    REGION_GZIP.write_bytes(gz)

    generated_at = os.environ.get("AVIATIONDB_GENERATED_AT") or datetime.now(UTC).isoformat()
    counts = _counts(payload)
    _copy_license_files(SHARED_AVIATION_DIR)
    coverage = _coverage_report(generated_at, counts)
    validation = _validation_report(generated_at, counts)

    _write_json(SHARED_AVIATION_DIR / "coverage_report.json", coverage)
    _write_json(SHARED_AVIATION_DIR / "validation_report.json", validation)

    manifest = _manifest(generated_at, raw, counts)
    _write_json(SHARED_AVIATION_DIR / "aviation-pack-manifest.json", manifest)

    _sync_public_pack()
    print(
        json.dumps(
            {
                "id": manifest["id"],
                "sourceMode": manifest["sourceMode"],
                "region": manifest["regions"][0]["id"],
                "points": counts["points"],
                "airways": counts["airways"],
                "segments": counts["segments"],
                "gzipBytes": len(gz),
            },
            indent=2,
        )
    )
    return 0


def _validate_flightgear_payload(payload: dict[str, Any]) -> None:
    if payload.get("region") != "global":
        raise SystemExit("FlightGear public pack must use region=global")
    for row in payload.get("points", []):
        if len(row) < 5 or row[4] != "flightgear":
            raise SystemExit("FlightGear public pack contains a non-FlightGear point")
    for row in payload.get("airways", []):
        if len(row) < 3 or row[2] != "flightgear":
            raise SystemExit("FlightGear public pack contains a non-FlightGear airway")
    if payload.get("airports"):
        raise SystemExit("FlightGear public pack should not mix airport rows from other sources")


def _counts(payload: dict[str, Any]) -> dict[str, int]:
    return {
        "airports": len(payload.get("airports", [])),
        "points": len(payload.get("points", [])),
        "airways": len(payload.get("airways", [])),
        "segments": len(payload.get("segments", [])),
    }


def _coverage_report(generated_at: str, counts: dict[str, int]) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "sourceMode": "flightgear-gpl-2.0",
        "license": _license_block(),
        "regions": {
            "global": {
                "countries": ["GLOBAL"],
                **counts,
            }
        },
        "known_points": {},
        "validation": {
            "errors": 0,
            "warnings": 0,
        },
    }


def _validation_report(generated_at: str, counts: dict[str, int]) -> dict[str, Any]:
    return {
        "generatedAt": generated_at,
        "sourceMode": "flightgear-gpl-2.0",
        "checks": {
            "onlyFlightGearRows": True,
            "globalRegion": True,
            "noMixedAirportRows": True,
            "points": counts["points"],
            "airways": counts["airways"],
            "segments": counts["segments"],
        },
        "issues": [],
    }


def _manifest(generated_at: str, raw: bytes, counts: dict[str, int]) -> dict[str, Any]:
    return {
        "id": "aviation-airgraph",
        "version": "0.2.0",
        "generatedAt": generated_at,
        "generatedFrom": f"sha256:{sha256(raw).hexdigest()}",
        "sourceMode": "flightgear-gpl-2.0",
        "licenseMode": "gpl-2.0-or-later",
        "license": _license_block(),
        "regions": [
            {
                "id": "global",
                "countries": ["GLOBAL"],
                **counts,
            }
        ],
        "sources": [
            {
                "sourceId": "flightgear",
                "provider": "FlightGear navdata",
                "country": None,
                "redistributionStatus": "redistribution_allowed",
                "airacCycle": "2013.10",
                "license": "GPL-2.0-or-later",
                "licenseUrl": "https://www.gnu.org/licenses/old-licenses/gpl-2.0.html",
                "sourceUrl": "https://sourceforge.net/p/flightgear/fgdata/ci/release/2024.1/tree/",
                "noticePath": f"shared/offline-packs/aviation/{NOTICE_RELATIVE}",
            }
        ],
        "payloads": {
            "airgraph": [
                _entry(
                    "shared/offline-packs/aviation/regions/global.airgraph.json.gz",
                    REGION_GZIP,
                    "application/json+gzip",
                )
            ],
            "notices": [
                _entry(f"shared/offline-packs/aviation/{NOTICE_RELATIVE}", SHARED_AVIATION_DIR / NOTICE_RELATIVE, "text/plain"),
                _entry(f"shared/offline-packs/aviation/{GPL_RELATIVE}", SHARED_AVIATION_DIR / GPL_RELATIVE, "text/plain"),
            ],
            "reports": [
                _entry("shared/offline-packs/aviation/coverage_report.json", SHARED_AVIATION_DIR / "coverage_report.json", "application/json"),
                _entry("shared/offline-packs/aviation/validation_report.json", SHARED_AVIATION_DIR / "validation_report.json", "application/json"),
            ],
        },
    }


def _license_block() -> dict[str, str]:
    return {
        "spdx": "GPL-2.0-or-later",
        "name": "GNU General Public License version 2",
        "noticePath": f"shared/offline-packs/aviation/{NOTICE_RELATIVE}",
        "licenseTextPath": f"shared/offline-packs/aviation/{GPL_RELATIVE}",
        "source": "FlightGear fgdata navdata",
        "sourceUrl": "https://sourceforge.net/p/flightgear/fgdata/ci/release/2024.1/tree/",
    }


def _entry(path: str, local_path: Path, content_type: str) -> dict[str, Any]:
    data = local_path.read_bytes()
    return {
        "path": path,
        "bytes": len(data),
        "sha256": sha256(data).hexdigest(),
        "contentType": content_type,
        "public": True,
    }


def _copy_license_files(root: Path) -> None:
    (root / "licenses").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(NOTICE_SOURCE, root / NOTICE_RELATIVE)
    shutil.copyfile(GPL_SOURCE, root / GPL_RELATIVE)


def _sync_public_pack() -> None:
    for root in (SHARED_AVIATION_DIR, PUBLIC_AVIATION_DIR):
        for relative in OBSOLETE_FILES:
            path = root / relative
            if path.exists():
                path.unlink()
    for relative in (
        "aviation-pack-manifest.json",
        "coverage_report.json",
        "validation_report.json",
        "regions/global.airgraph.json",
        "regions/global.airgraph.json.gz",
        NOTICE_RELATIVE,
        GPL_RELATIVE,
    ):
        source = SHARED_AVIATION_DIR / relative
        target = PUBLIC_AVIATION_DIR / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _gzip_bytes(payload: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as handle:
        handle.write(payload)
    return output.getvalue()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
