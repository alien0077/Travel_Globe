#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
DEFAULT_FUSION = (
    PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "route-source-fusion.global.json"
)
DEFAULT_SUSPICIOUS = (
    PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "suspicious-airports.global.json"
)
DEFAULT_RELEASE_DIR = PROJECT / "data" / "releases" / "private" / "route-fallback"
DEFAULT_SHARED_DIR = ROOT / "shared" / "offline-packs" / "route-fallback"
DEFAULT_PUBLIC_DIR = ROOT / "replay-engine" / "public" / "offline-packs" / "route-fallback"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a compact global airport-pair fallback route pack.")
    parser.add_argument("--fusion", type=Path, default=DEFAULT_FUSION)
    parser.add_argument("--suspicious", type=Path, default=DEFAULT_SUSPICIOUS)
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    parser.add_argument("--shared-dir", type=Path, default=DEFAULT_SHARED_DIR)
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    args = parser.parse_args()

    fusion = json.loads(args.fusion.read_text(encoding="utf-8"))
    suspicious = json.loads(args.suspicious.read_text(encoding="utf-8"))
    pack = build_route_fallback_pack(fusion, suspicious)
    raw = json.dumps(pack, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    gz = gzip.compress(raw, compresslevel=9)

    manifest = {
        "schemaVersion": 1,
        "generatedAt": pack["generatedAt"],
        "pack": "global.route-fallback.json.gz",
        "summary": pack["summary"],
        "sourceRegistry": pack["sourceRegistry"],
        "bytes": {
            "json": len(raw),
            "gzip": len(gz),
        },
    }
    manifest_raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"

    for target_dir in [args.release_dir, args.shared_dir, args.public_dir]:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "global.route-fallback.json.gz").write_bytes(gz)
        (target_dir / "manifest.json").write_bytes(manifest_raw)

    print(
        json.dumps(
            {
                "releaseDir": str(args.release_dir),
                "sharedDir": str(args.shared_dir),
                "publicDir": str(args.public_dir),
                "summary": pack["summary"],
                "bytes": manifest["bytes"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_route_fallback_pack(fusion: dict[str, Any], suspicious: dict[str, Any]) -> dict[str, Any]:
    routes = [compact_route(route) for route in fusion.get("routes", [])]
    routes.sort(key=lambda route: route["id"])
    suspicious_airports = [compact_suspicious_airport(row) for row in suspicious.get("airports", [])]
    suspicious_airports.sort(key=lambda row: (severity_rank(row["severity"]), row["routeGraphScore"]), reverse=True)
    summary = {
        "routes": len(routes),
        "observedRoutes": sum(1 for route in routes if route["hasObservedAdsb"]),
        "fallbackRoutes": sum(1 for route in routes if route["requiresFallbackShape"]),
        "connectivityFallbackRoutes": sum(
            1 for route in routes if route["bestSource"] == "airport_connectivity_fallback"
        ),
        "suspiciousAirports": len(suspicious_airports),
        "criticalSuspiciousAirports": sum(1 for row in suspicious_airports if row["severity"] == "critical"),
    }
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourceRegistry": {
            key: {
                "defaultConfidence": value.get("defaultConfidence"),
                "offlineRedistribution": value.get("offlineRedistribution"),
            }
            for key, value in (fusion.get("sourceRegistry") or {}).items()
        },
        "summary": summary,
        "routes": routes,
        "suspiciousAirports": suspicious_airports,
    }


def compact_route(route: dict[str, Any]) -> dict[str, Any]:
    sources = route.get("sources") or []
    return {
        "id": route["id"],
        "originIata": route["originIata"],
        "destinationIata": route["destinationIata"],
        "bestSource": route["bestSource"],
        "routeScore": route["routeScore"],
        "hasObservedAdsb": route["hasObservedAdsb"],
        "requiresFallbackShape": route["requiresFallbackShape"],
        "sourceTypes": [source.get("type") for source in sources if source.get("type")],
        "observedSampleCount": first_number(sources, "observed_adsb", "sampleCount"),
        "observedVariantCount": first_number(sources, "observed_adsb", "variantCount"),
        "openFlightsCount": first_number(sources, "static_route_graph", "openFlightsCount"),
        "aircraftTypes": first_list(sources, "static_route_graph", "aircraftTypes"),
        "connectivityFallback": first_connectivity_fallback(sources),
    }


def compact_suspicious_airport(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "iata": row["iata"],
        "icao": row.get("icao"),
        "countryCode": row.get("countryCode"),
        "airportType": row.get("airportType"),
        "severity": row["severity"],
        "routeGraphScore": row["routeGraphScore"],
        "routeGraphDestinations": row["routeGraphDestinations"],
        "observedEndpointRoutes": row["observedEndpointRoutes"],
        "observedEndpointSamples": row["observedEndpointSamples"],
    }


def first_number(sources: list[dict[str, Any]], source_type: str, key: str) -> int | None:
    for source in sources:
        if source.get("type") == source_type and source.get(key) is not None:
            return int(source[key])
    return None


def first_list(sources: list[dict[str, Any]], source_type: str, key: str) -> list[str]:
    for source in sources:
        if source.get("type") == source_type:
            return list(source.get(key) or [])
    return []


def first_connectivity_fallback(sources: list[dict[str, Any]]) -> dict[str, Any] | None:
    for source in sources:
        if source.get("type") == "airport_connectivity_fallback":
            return {
                "reason": source.get("reason"),
                "anchorIata": source.get("anchorIata"),
                "distanceKm": source.get("distanceKm"),
            }
    return None


def severity_rank(value: str) -> int:
    return {"critical": 3, "high": 2, "medium": 1, "low": 0}.get(value, -1)


if __name__ == "__main__":
    raise SystemExit(main())
