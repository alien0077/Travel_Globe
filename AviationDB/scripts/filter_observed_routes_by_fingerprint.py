#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Filter observed ADS-B routes by route-level geometry fingerprints.")
    parser.add_argument("--observed", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seen-index", type=Path)
    parser.add_argument("--write-new-index", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--fingerprint-mode",
        choices=("pair", "signature"),
        default="signature",
        help="Use airport-pair coverage keys or exact representative geometry signatures.",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Write route fingerprints from the observed pack without writing a filtered observed pack.",
    )
    args = parser.parse_args()

    pack = read_json(args.observed)
    routes = pack.get("routes", [])
    seen = read_index(args.seen_index) if args.seen_index else set()
    new_keys: list[str] = []
    new_key_set: set[str] = set()
    filtered_routes: list[dict[str, Any]] = []
    skipped_seen = 0
    skipped_duplicate = 0
    missing_fingerprint = 0

    for route in routes:
        key = route_fingerprint_key(route, mode=args.fingerprint_mode)
        if not key:
            missing_fingerprint += 1
            if not args.index_only:
                filtered_routes.append(route)
            continue
        if key in seen:
            skipped_seen += 1
            continue
        if key in new_key_set:
            skipped_duplicate += 1
            continue
        new_key_set.add(key)
        new_keys.append(key)
        if not args.index_only:
            filtered_routes.append(route)

    args.write_new_index.parent.mkdir(parents=True, exist_ok=True)
    args.write_new_index.write_text("\n".join(new_keys) + ("\n" if new_keys else ""), encoding="utf-8")

    if not args.index_only:
        if not args.output:
            raise SystemExit("--output is required unless --index-only is set")
        output_pack = {**pack, "routes": filtered_routes}
        output_pack["dedupe"] = {
            "schemaVersion": 1,
            "generatedAt": now_iso(),
            "sourceObservedPack": str(args.observed),
            "seenIndex": str(args.seen_index) if args.seen_index else None,
            "fingerprintPolicy": fingerprint_policy(args.fingerprint_mode),
            "fingerprintMode": args.fingerprint_mode,
            "inputRoutes": len(routes),
            "outputRoutes": len(filtered_routes),
            "skippedSeenFingerprints": skipped_seen,
            "skippedDuplicateFingerprintsInPack": skipped_duplicate,
            "routesWithoutFingerprint": missing_fingerprint,
            "newFingerprints": len(new_keys),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output, output_pack)

    report = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "sourceObservedPack": str(args.observed),
        "outputObservedPack": str(args.output) if args.output else None,
        "seenIndex": str(args.seen_index) if args.seen_index else None,
        "newIndex": str(args.write_new_index),
        "fingerprintPolicy": fingerprint_policy(args.fingerprint_mode),
        "fingerprintMode": args.fingerprint_mode,
        "inputRoutes": len(routes),
        "outputRoutes": len(filtered_routes) if not args.index_only else 0,
        "skippedSeenFingerprints": skipped_seen,
        "skippedDuplicateFingerprintsInPack": skipped_duplicate,
        "routesWithoutFingerprint": missing_fingerprint,
        "newFingerprints": len(new_keys),
        "indexOnly": args.index_only,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def route_fingerprint_key(route: dict[str, Any], *, mode: str) -> str | None:
    origin = str(route.get("originIata") or "").strip().upper()
    destination = str(route.get("destinationIata") or "").strip().upper()
    if not origin or not destination:
        return None
    if mode == "pair":
        return f"{origin}-{destination}"
    representative = route.get("representative") if isinstance(route.get("representative"), dict) else {}
    signature = str(representative.get("signature") or "").strip()
    if not signature:
        return None
    return f"{origin}-{destination}|{signature}"


def fingerprint_policy(mode: str) -> str:
    if mode == "pair":
        return "originIata-destinationIata coverage key"
    return "originIata-destinationIata + representative.signature"


def read_index(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def read_json(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        return
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
