#!/usr/bin/env python3
"""Complete missing reverse route shapes with validated directed-airway paths."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))

from aviationdb.ifr_routing import (  # noqa: E402
    DEFAULT_COST_CONFIG,
    DirectedAirgraph,
    select_ifr_route_shape_from_graph,
)

DEFAULT_AIRPORT_INDEX = ROOT / "shared/offline-packs/core-global/airports-index.json"
DEFAULT_AIRGRAPH = ROOT / "shared/offline-packs/aviation/regions/global.airgraph.json"
DEFAULT_SHARED = ROOT / "shared/offline-packs/route-shapes/global.route-shapes.runtime.json"
DEFAULT_PUBLIC = ROOT / "replay-engine/public/offline-packs/route-shapes/global.route-shapes.runtime.json"
DEFAULT_COMPLETION_PACK = ROOT / "shared/offline-packs/route-shapes/global.route-shapes.runtime-completions.json"
DEFAULT_REPORT = Path("/private/tmp/travel-globe-missing-reverse-route-report.json")
DEFAULT_STATUS = Path("/private/tmp/travel-globe-missing-reverse-route-status.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--airgraph", type=Path, default=DEFAULT_AIRGRAPH)
    parser.add_argument("--runtime-input", type=Path, default=DEFAULT_SHARED)
    parser.add_argument("--shared-output", type=Path, default=DEFAULT_SHARED)
    parser.add_argument("--public-output", type=Path, default=DEFAULT_PUBLIC)
    parser.add_argument("--completion-pack", type=Path, default=DEFAULT_COMPLETION_PACK)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--add-reverse-fallback", action="store_true", help="Use the existing forward geometry reversed when no validated reverse path exists.")
    args = parser.parse_args()

    airports = airport_lookup(args.airport_index)
    runtime = json.loads(args.runtime_input.read_text(encoding="utf-8"))
    routes = runtime.get("routes") if isinstance(runtime.get("routes"), dict) else {}
    graph = DirectedAirgraph(json.loads(args.airgraph.read_text(encoding="utf-8")), DEFAULT_COST_CONFIG)

    missing = missing_reverse_route_ids(routes)
    if args.limit is not None:
        missing = missing[: args.limit]
    args.status.parent.mkdir(parents=True, exist_ok=True)
    write_status(args.status, "running", attempted=len(missing), processed=0, added=0, unresolved=0)
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "input": str(args.runtime_input),
        "dryRun": args.dry_run,
        "addReverseFallback": args.add_reverse_fallback,
        "attempted": len(missing),
        "added": [],
        "reverseFallbackAdded": [],
        "unresolved": [],
    }
    completion_routes: dict[str, Any] = {}
    if args.completion_pack.exists():
        existing_completion = json.loads(args.completion_pack.read_text(encoding="utf-8"))
        existing_routes = existing_completion.get("routes") if isinstance(existing_completion, dict) else None
        if isinstance(existing_routes, dict):
            # A later keepalive/retry may find no missing reverse IDs.  Never
            # replace a completed, reproducible overlay with an empty file.
            completion_routes.update(existing_routes)

    for index, reverse_id in enumerate(missing, 1):
        origin_iata, destination_iata = reverse_id.split("-", 1)
        origin = airports.get(origin_iata)
        destination = airports.get(destination_iata)
        if not origin or not destination:
            report["unresolved"].append({"route": reverse_id, "reason": "missing_airport"})
            continue

        result = select_ifr_route_shape_from_graph(
            graph,
            origin,
            destination,
            route_id=reverse_id,
            pair_source={"exists": False, "source": "validated_reverse_completion"},
            adsb_support={},
            k=1,
        )
        if result.get("routeUnavailable") or not result.get("selected"):
            forward_id = reverse_id.split("-", 1)[1] + "-" + reverse_id.split("-", 1)[0]
            forward = routes.get(forward_id)
            if args.add_reverse_fallback and isinstance(forward, dict) and forward.get("p"):
                fallback = reverse_route_fallback(reverse_id, forward_id, forward)
                if not args.dry_run:
                    routes[reverse_id] = fallback
                    completion_routes[reverse_id] = fallback
                report["reverseFallbackAdded"].append({
                    "route": reverse_id,
                    "sourceRoute": forward_id,
                    "points": len(fallback["p"]),
                })
                continue
            report["unresolved"].append({
                "route": reverse_id,
                "reason": result.get("unavailableReason") or "route_unavailable",
                "connectorDiagnostics": result.get("connectorDiagnostics") or {},
            })
            continue

        selected = result["selected"]
        compact = compact_route(selected)
        if not args.dry_run:
            routes[reverse_id] = compact
            completion_routes[reverse_id] = compact
        report["added"].append({
            "route": reverse_id,
            "method": compact["m"],
            "score": compact["s"],
            "points": len(compact["p"]),
            "originConnector": connector_ident(selected, "originConnector"),
            "destinationConnector": connector_ident(selected, "destinationConnector"),
        })
        if index % 100 == 0:
            print(json.dumps({"processed": index, "attempted": len(missing), "added": len(report["added"])}, ensure_ascii=False))
            write_status(args.status, "running", attempted=len(missing), processed=index, added=len(report["added"]), unresolved=len(report["unresolved"]))

    report["addedCount"] = len(report["added"])
    report["reverseFallbackAddedCount"] = len(report["reverseFallbackAdded"])
    report["unresolvedCount"] = len(report["unresolved"])
    report["outputRouteCount"] = len(routes)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_status(args.status, "complete", attempted=len(missing), processed=len(missing), added=len(report["added"]), reverseFallbackAdded=len(report["reverseFallbackAdded"]), unresolved=len(report["unresolved"]), report=str(args.report))

    if not args.dry_run:
        runtime["routes"] = routes
        summary = runtime.setdefault("meta", {}).setdefault("summary", {})
        previous_added = int(summary.get("reverseCompletionAdded") or 0)
        previous_fallback = int(summary.get("reverseFallbackAdded") or 0)
        summary["reverseCompletionAttempted"] = len(missing)
        summary["reverseCompletionAdded"] = previous_added + len(report["added"])
        summary["reverseFallbackAdded"] = previous_fallback + len(report["reverseFallbackAdded"])
        summary["reverseCompletionUnresolved"] = len(report["unresolved"])
        for output in {args.shared_output, args.public_output}:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(runtime, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
            update_manifest(output, runtime)
        args.completion_pack.parent.mkdir(parents=True, exist_ok=True)
        args.completion_pack.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "source": "repair_missing_reverse_route_shapes",
                    "generatedAt": report["generatedAt"],
                    "routes": completion_routes,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )

    print(json.dumps({
        "attempted": len(missing),
        "added": len(report["added"]),
        "reverseFallbackAdded": len(report["reverseFallbackAdded"]),
        "unresolved": len(report["unresolved"]),
        "report": str(args.report),
        "dryRun": args.dry_run,
    }, ensure_ascii=False, indent=2))
    # Unresolved routes are a data-quality report, not a command failure. The
    # pipeline must still publish the validated completions and retain the
    # report for follow-up source-data work.
    return 0


def airport_lookup(path: Path) -> dict[str, dict[str, Any]]:
    airports: dict[str, dict[str, Any]] = {}
    for airport in json.loads(path.read_text(encoding="utf-8")).get("airports", []):
        for key in (airport.get("iataCode"), airport.get("icaoCode"), airport.get("ident")):
            if key:
                airports[str(key).upper()] = airport
    return airports


def missing_reverse_route_ids(routes: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for route_id in sorted(routes):
        if "-" not in route_id:
            continue
        origin, destination = route_id.split("-", 1)
        reverse_id = f"{destination}-{origin}"
        if reverse_id not in routes:
            missing.append(reverse_id)
    return missing


def compact_route(selected: dict[str, Any]) -> dict[str, Any]:
    metrics = selected.get("metrics") if isinstance(selected.get("metrics"), dict) else {}
    distance_km = metrics.get("distanceKm")
    if distance_km is None:
        distance_km = float(metrics.get("distanceNm") or 0) * 1.852
    provenance = selected.get("provenance") if isinstance(selected.get("provenance"), dict) else {}
    warnings = []
    if provenance.get("warning"):
        warnings.append(str(provenance["warning"]))
    if selected.get("method") == "directed_airway_graph":
        warnings.append("IFR airway estimate from the local airgraph; not an observed ADS-B flight track.")
    return {
        "m": selected.get("method"),
        "s": round(float(selected.get("score") or 0), 2),
        "d": round(float(distance_km) * 1000),
        "w": warnings,
        "p": [
            [point.get("ident"), point.get("lat"), point.get("lon"), point.get("pointType")]
            for point in selected.get("points", [])
        ],
    }


def reverse_route_fallback(route_id: str, source_route_id: str, source_route: dict[str, Any]) -> dict[str, Any]:
    return {
        "m": "reverse_route_fallback",
        "s": source_route.get("s"),
        "d": source_route.get("d"),
        "w": [
            f"Reverse geometry fallback from {source_route_id}; the reverse directed airway path was unavailable.",
            "Not IFR-validated; visual approximation only.",
        ],
        "p": list(reversed(source_route.get("p") or [])),
    }


def connector_ident(selected: dict[str, Any], key: str) -> str | None:
    provenance = selected.get("provenance") if isinstance(selected.get("provenance"), dict) else {}
    connector = provenance.get(key) if isinstance(provenance.get(key), dict) else {}
    value = connector.get("ident")
    return str(value) if value is not None else None


def update_manifest(output: Path, runtime: dict[str, Any]) -> None:
    manifest = output.with_name("manifest.json")
    if not manifest.exists():
        return
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["runtimePack"] = output.name
    payload.setdefault("bytes", {})["runtimeJson"] = output.stat().st_size
    payload.setdefault("summary", {}).update(runtime.get("meta", {}).get("summary", {}))
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_status(path: Path, state: str, **extra: Any) -> None:
    path.write_text(json.dumps({"state": state, "updatedAt": datetime.now(UTC).isoformat(), **extra}, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
