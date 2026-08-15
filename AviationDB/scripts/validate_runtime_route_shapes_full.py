#!/usr/bin/env python3
"""Run release-gate QA over every route published to the runtime pack.

This is intentionally different from the reference-corridor sample QA.  The
unit under test is the artifact the web/iOS replay actually reads.  Every
runtime route is checked for:

* reproducibility from the base route pack plus selection overlays;
* valid, continuous endpoint geometry;
* distance/geometry consistency; and
* explicit evidence classification (observed, IFR estimate, fallback, or
  undocumented runtime-only completion).

The script does not call an IFR route "observed" merely because it connects
two airports.  A structurally valid IFR estimate is still reported as an
estimate and cannot silently become a validated ADS-B route.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
DEFAULT_BASE = ROOT / "shared/offline-packs/route-shapes/global.route-shapes.json.gz"
DEFAULT_RUNTIME = ROOT / "shared/offline-packs/route-shapes/global.route-shapes.runtime.json"
DEFAULT_SELECTION_DIR = ROOT / "shared/offline-packs/route-shapes"
DEFAULT_COMPLETION_PACK = DEFAULT_SELECTION_DIR / "global.route-shapes.runtime-completions.json"
DEFAULT_CORRIDOR_PACK = DEFAULT_SELECTION_DIR / "global.route-shapes.runtime-corridor-025.json"
DEFAULT_AIRPORT_INDEX = ROOT / "shared/offline-packs/core-global/airports-index.json"
DEFAULT_OUTPUT = Path("/private/tmp/travel-globe-runtime-route-shape-full-qa.json")
EARTH_RADIUS_KM = 6371.0088
MAX_DISTANCE_RATIO = 1.50
MAX_SEGMENT_WARNING_KM = 500.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--selection-dir", type=Path, default=DEFAULT_SELECTION_DIR)
    parser.add_argument("--completion-pack", type=Path, default=DEFAULT_COMPLETION_PACK)
    parser.add_argument("--corridor-pack", type=Path, default=DEFAULT_CORRIDOR_PACK)
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--strict", action="store_true", help="Return non-zero when the release gate is blocked.")
    args = parser.parse_args()

    exporter = load_exporter()
    base = read_json_gz(args.base)
    runtime_payload = read_json(args.runtime)
    runtime = runtime_payload.get("routes") if isinstance(runtime_payload.get("routes"), dict) else {}
    expected, source_by_route, selection_meta = reconstruct_expected(base, args.selection_dir, args.completion_pack, args.corridor_pack, exporter)
    aliases = airport_aliases(args.airport_index)

    parity = compare_runtime(expected, runtime, source_by_route)
    route_reports: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    evidence_counts: Counter[str] = Counter()
    error_counts: Counter[str] = Counter()
    large_segments: list[dict[str, Any]] = []

    for route_id in sorted(runtime):
        route = runtime[route_id]
        source = source_by_route.get(route_id, "runtime_only")
        source_counts[source] += 1
        report = inspect_route(route_id, route, aliases)
        report["source"] = source
        report["parityIssues"] = parity["issuesByRoute"].get(route_id, [])
        report["evidenceClass"] = evidence_class(route, selection_meta.get(route_id))
        evidence_counts[report["evidenceClass"]] += 1
        if report["maxSegmentKm"] > MAX_SEGMENT_WARNING_KM:
            large_segments.append(
                {
                    "route": route_id,
                    "maxSegmentKm": report["maxSegmentKm"],
                    "from": report["maxSegmentFrom"],
                    "to": report["maxSegmentTo"],
                }
            )
        for error in report["errors"]:
            error_counts[error] += 1
        route_reports.append(report)

    structural_failures = [item for item in route_reports if item["errors"]]
    provenance_failures = [
        item
        for item in route_reports
        if item["source"] == "runtime_only"
        or item["evidenceClass"] in {"missing_provenance", "ifr_estimate_missing_warning"}
    ]
    parity_passed = not parity["missing"] and not parity["extra"] and not parity["mismatches"]
    qa_passed = parity_passed and not structural_failures and not provenance_failures

    payload = {
        "schemaVersion": 1,
        "evidenceType": "runtime_route_shape_full_qa_v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "inputs": {
            "base": str(args.base),
            "runtime": str(args.runtime),
            "selectionDir": str(args.selection_dir),
            "completionPack": str(args.completion_pack),
            "corridorPack": str(args.corridor_pack),
            "airportIndex": str(args.airport_index),
        },
        "policy": {
            "allRuntimeRoutesEvaluated": True,
            "runtimeMustBeReproducible": True,
            "observedAdsBIsNotInferredFromEndpointConnectivity": True,
            "ifrEstimateIsNotObservedEvidence": True,
            "maxDeclaredDistanceRatio": MAX_DISTANCE_RATIO,
            "largeSegmentWarningKm": MAX_SEGMENT_WARNING_KM,
        },
        "summary": {
            "runtimeRouteCount": len(runtime),
            "evaluatedRouteCount": len(route_reports),
            "baseRouteCount": len(base.get("routeShapes", [])),
            "selectionFileCount": len(selection_meta),
            "sourceCounts": dict(sorted(source_counts.items())),
            "evidenceCounts": dict(sorted(evidence_counts.items())),
            "structuralFailureCount": len(structural_failures),
            "provenanceFailureCount": len(provenance_failures),
            "largeSegmentWarningCount": len(large_segments),
            "errorCounts": dict(sorted(error_counts.items())),
        },
        "parity": {
            "passed": parity_passed,
            "expectedRouteCount": len(expected),
            "runtimeRouteCount": len(runtime),
            "missingCount": len(parity["missing"]),
            "extraCount": len(parity["extra"]),
            "mismatchCount": len(parity["mismatches"]),
            "missing": parity["missing"],
            "extra": parity["extra"],
            "mismatches": parity["mismatches"],
        },
        "releaseGate": {
            "passed": qa_passed,
            "blockedReasons": blocked_reasons(parity, structural_failures, provenance_failures),
            "structuralFailures": structural_failures,
            "provenanceFailures": provenance_failures,
        },
        "selectionOverlays": selection_meta,
        "largeSegmentWarnings": sorted(large_segments, key=lambda item: item["maxSegmentKm"], reverse=True)[:100],
        "routes": route_reports,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": "complete",
        "output": str(args.output),
        "summary": payload["summary"],
        "parity": payload["parity"] | {"missing": len(parity["missing"]), "extra": len(parity["extra"]), "mismatches": len(parity["mismatches"])},
        "releaseGate": {
            "passed": payload["releaseGate"]["passed"],
            "blockedReasons": payload["releaseGate"]["blockedReasons"],
            "structuralFailureRoutes": [item["route"] for item in structural_failures],
            "provenanceFailureCount": len(provenance_failures),
        },
    }, ensure_ascii=False, indent=2))
    return 2 if args.strict and not qa_passed else 0


def load_exporter():
    path = PROJECT / "scripts/export_route_shapes_runtime_pack.py"
    spec = importlib.util.spec_from_file_location("route_shape_runtime_exporter", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load exporter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def read_json_gz(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def reconstruct_expected(base: dict[str, Any], selection_dir: Path, completion_path: Path, corridor_path: Path, exporter) -> tuple[dict[str, Any], dict[str, str], dict[str, dict[str, Any]]]:
    expected: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for route in base.get("routeShapes", []):
        route_id = route.get("id")
        if exporter.add_runtime_route(expected, route_id, route):
            sources[str(route_id)] = "base"

    completion = read_json(completion_path) if completion_path.exists() else {}
    completion_routes = completion.get("routes") if isinstance(completion.get("routes"), dict) else {}
    for route_id, route in sorted(completion_routes.items()):
        if exporter.add_compact_runtime_route(expected, route_id, route):
            sources[str(route_id)] = "completion_pack"

    if corridor_path.exists():
        corridor = read_json(corridor_path)
        corridor_routes = corridor.get("routes") if isinstance(corridor.get("routes"), dict) else {}
        for route_id, route in sorted(corridor_routes.items()):
            if exporter.add_compact_runtime_route(expected, route_id, route):
                sources[str(route_id)] = "corridor_025"

    selection_meta: dict[str, dict[str, Any]] = {}
    for path in sorted(selection_dir.glob("*.shape-selection.json")):
        selection = read_json(path)
        if selection.get("routeUnavailable"):
            continue
        route_id = str(selection.get("route") or path.name.removesuffix(".shape-selection.json"))
        selected = selection.get("selected")
        if not isinstance(selected, dict):
            continue
        if (
            selected.get("method") == "directed_airway_graph"
            and isinstance(expected.get(route_id), dict)
            and expected[route_id].get("m") == "corridor_025_graph"
        ):
            continue
        if exporter.add_runtime_route(expected, route_id, selected):
            sources[route_id] = "selection_override"
            provenance = selected.get("provenance") if isinstance(selected.get("provenance"), dict) else {}
            selection_meta[route_id] = {
                "file": str(path),
                "method": selected.get("method"),
                "provenance": provenance,
                "points": len(selected.get("points") or []),
            }
    return expected, sources, selection_meta


def compare_runtime(expected: dict[str, Any], runtime: dict[str, Any], sources: dict[str, str]) -> dict[str, Any]:
    expected_ids = set(expected)
    runtime_ids = set(runtime)
    missing = sorted(expected_ids - runtime_ids)
    extra = sorted(runtime_ids - expected_ids)
    mismatches = []
    issues_by_route: dict[str, list[str]] = {}
    for route_id in sorted(expected_ids & runtime_ids):
        if expected[route_id] != runtime[route_id]:
            mismatches.append(route_id)
            issues_by_route.setdefault(route_id, []).append("runtime_does_not_match_reconstructed_source")
    for route_id in missing:
        issues_by_route.setdefault(route_id, []).append("runtime_missing_reconstructed_route")
    for route_id in extra:
        issues_by_route.setdefault(route_id, []).append("runtime_route_has_no_reconstructable_source")
    return {"missing": missing, "extra": extra, "mismatches": mismatches, "issuesByRoute": issues_by_route}


def airport_aliases(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    payload = read_json(path)
    aliases: dict[str, str] = {}
    for airport in payload.get("airports", []):
        if not isinstance(airport, dict):
            continue
        iata = str(airport.get("iataCode") or "").upper()
        if not iata:
            continue
        aliases[iata] = iata
        for key in (airport.get("icaoCode"), airport.get("ident")):
            if key:
                aliases[str(key).upper()] = iata
    return aliases


def inspect_route(route_id: str, route: Any, aliases: dict[str, str]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(route, dict):
        return {
            "route": route_id,
            "method": None,
            "points": 0,
            "errors": ["route_not_object"],
            "maxSegmentKm": 0.0,
            "maxSegmentFrom": None,
            "maxSegmentTo": None,
        }
    points = route.get("p") if isinstance(route.get("p"), list) else []
    method = route.get("m")
    if len(points) < 2:
        errors.append("fewer_than_two_points")

    endpoint_parts = route_id.split("-", 1)
    if len(endpoint_parts) != 2:
        errors.append("route_id_not_origin_destination")
        endpoint_parts = ["", ""]
    expected_start, expected_end = (part.upper() for part in endpoint_parts)
    actual_start = str(points[0][0] or "").upper() if points and isinstance(points[0], list) and points[0] else ""
    actual_end = str(points[-1][0] or "").upper() if points and isinstance(points[-1], list) and points[-1] else ""
    alias_used = []
    if not endpoint_matches(expected_start, actual_start, aliases):
        errors.append("origin_endpoint_mismatch")
    elif expected_start != actual_start:
        alias_used.append({"side": "origin", "routeId": expected_start, "point": actual_start})
    if not endpoint_matches(expected_end, actual_end, aliases):
        errors.append("destination_endpoint_mismatch")
    elif expected_end != actual_end:
        alias_used.append({"side": "destination", "routeId": expected_end, "point": actual_end})

    path_km = 0.0
    max_segment = (0.0, None, None)
    for index, point in enumerate(points):
        if not isinstance(point, list) or len(point) < 4:
            errors.append("malformed_point")
            continue
        try:
            lat = float(point[1])
            lon = float(point[2])
        except (TypeError, ValueError):
            errors.append("non_numeric_coordinate")
            continue
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            errors.append("coordinate_out_of_range")
        if not point[0]:
            errors.append("point_missing_ident")
        if not point[3]:
            errors.append("point_missing_type")
        if index and isinstance(points[index - 1], list) and len(points[index - 1]) >= 3:
            try:
                segment = haversine(points[index - 1][1], points[index - 1][2], lat, lon)
            except (TypeError, ValueError):
                continue
            path_km += segment
            if segment > max_segment[0]:
                max_segment = (segment, points[index - 1][0], point[0])

    declared_km = safe_float(route.get("d")) / 1000.0
    ratio = path_km / declared_km if declared_km > 0 else 0.0
    if declared_km <= 0:
        errors.append("missing_declared_distance")
    elif ratio > MAX_DISTANCE_RATIO or ratio < 1 / MAX_DISTANCE_RATIO:
        errors.append("geometry_distance_mismatch")

    # Duplicate errors are noise when one malformed point triggers multiple
    # checks.  Keep deterministic order for diffable reports.
    errors = list(dict.fromkeys(errors))
    return {
        "route": route_id,
        "method": method,
        "points": len(points),
        "errors": errors,
        "geometryQaPassed": not errors,
        "pathKm": round(path_km, 3),
        "declaredKm": round(declared_km, 3),
        "pathToDeclaredRatio": round(ratio, 5),
        "maxSegmentKm": round(max_segment[0], 3),
        "maxSegmentFrom": max_segment[1],
        "maxSegmentTo": max_segment[2],
        "endpointAliases": alias_used,
        "warnings": route.get("w") if isinstance(route.get("w"), list) else [],
    }


def endpoint_matches(expected: str, actual: str, aliases: dict[str, str]) -> bool:
    return expected == actual or (aliases.get(expected, expected) == aliases.get(actual, actual))


def evidence_class(route: dict[str, Any], selection: dict[str, Any] | None) -> str:
    if not isinstance(route, dict):
        return "missing_provenance"
    method = route.get("m")
    warnings = route.get("w") if isinstance(route.get("w"), list) else []
    if method in {"observed_adsb_mapped", "recovered_endpoint"}:
        if selection and isinstance(selection.get("provenance"), dict):
            classification = selection["provenance"].get("validationClassification")
            if classification:
                return str(classification)
        return "observed_adsb_review"
    if method == "directed_airway_graph":
        return "ifr_estimate" if warnings else "ifr_estimate_missing_warning"
    if method == "corridor_025_graph":
        return "corridor_025_graph"
    if method == "approximate_direct_fallback":
        return "approximate_fallback"
    if method == "reverse_route_fallback":
        return "reverse_fallback"
    return "missing_provenance"


def blocked_reasons(parity: dict[str, Any], structural: list[dict[str, Any]], provenance: list[dict[str, Any]]) -> list[str]:
    reasons = []
    if parity["missing"]:
        reasons.append("runtime_missing_reconstructed_routes")
    if parity["extra"]:
        reasons.append("runtime_contains_routes_without_reconstructable_source")
    if parity["mismatches"]:
        reasons.append("runtime_geometry_or_metadata_differs_from_source")
    if structural:
        reasons.append("runtime_routes_fail_geometry_checks")
    if provenance:
        reasons.append("runtime_routes_lack_reproducible_or_explicit_provenance")
    return reasons


def safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def haversine(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> float:
    lat1_r, lat2_r = math.radians(float(lat1)), math.radians(float(lat2))
    dlat = lat2_r - lat1_r
    dlon = math.radians(float(lon2) - float(lon1))
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(min(1.0, value)))


if __name__ == "__main__":
    raise SystemExit(main())
