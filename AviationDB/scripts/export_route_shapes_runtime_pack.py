#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
DEFAULT_INPUT = ROOT / "shared" / "offline-packs" / "route-shapes" / "global.route-shapes.json.gz"
DEFAULT_SHARED = ROOT / "shared" / "offline-packs" / "route-shapes" / "global.route-shapes.runtime.json"
DEFAULT_PUBLIC = ROOT / "replay-engine" / "public" / "offline-packs" / "route-shapes" / "global.route-shapes.runtime.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export compact runtime JSON for Replay Engine route-shapes lookup.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--shared-output", type=Path, default=DEFAULT_SHARED)
    parser.add_argument("--public-output", type=Path, default=DEFAULT_PUBLIC)
    args = parser.parse_args()

    pack = read_json_gz(args.input)
    routes = {}
    for route in pack.get("routeShapes", []):
        route_id = route.get("id")
        if not route_id:
            continue
        metrics = route.get("metrics") if isinstance(route.get("metrics"), dict) else {}
        routes[route_id] = {
            "m": route.get("method"),
            "s": safe_number(route.get("score"), precision=2),
            "d": round(safe_number(metrics.get("distanceKm")) * 1000),
            "p": [
                [point.get("ident"), point.get("lat"), point.get("lon"), point.get("pointType")]
                for point in route.get("points", [])
                if isinstance(point, dict)
            ],
        }

    payload = {
        "meta": {
            "schemaVersion": 1,
            "generatedAt": pack.get("generatedAt"),
            "sourcePack": args.input.name,
            "summary": pack.get("summary"),
        },
        "routes": routes,
    }
    for output in [args.shared_output, args.public_output]:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        update_manifest(output)
    print(
        json.dumps(
            {
                "routes": len(routes),
                "sharedOutput": str(args.shared_output),
                "sharedBytes": args.shared_output.stat().st_size,
                "publicOutput": str(args.public_output),
                "publicBytes": args.public_output.stat().st_size,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def read_json_gz(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def safe_number(value: Any, precision: int | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(number):
        return 0
    return round(number, precision) if precision is not None else number


def update_manifest(runtime_path: Path) -> None:
    manifest_path = runtime_path.with_name("manifest.json")
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtimePack"] = runtime_path.name
    manifest.setdefault("bytes", {})["runtimeJson"] = runtime_path.stat().st_size
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
