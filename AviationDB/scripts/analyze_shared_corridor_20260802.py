#!/usr/bin/env python3
"""Build one-pass shared-corridor evidence from the retained 2026-08-02 raw.

This is deliberately an evidence report, not a route publisher.  It ignores the
airport-pair label assigned by the old nearest-airport builder and projects raw
legs onto a broad BKK -> current KHH-NRT validation-path baseline.  Legs that
cover overlapping portions of that baseline are counted as shared corridor
support.  The output keeps the KHH join distance and uncertainty explicit.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))

from aviationdb.observed_routes import (  # noqa: E402
    BuildOptions,
    haversine_km,
    iter_trace_payloads_from_split_tar,
    parse_trace_points,
    route_distance_km,
    split_legs,
)


DEFAULT_RAW_DIR = PROJECT / "data" / "raw" / "adsblol" / "2026-08-02"
DEFAULT_RUNTIME = ROOT / "shared" / "offline-packs" / "route-shapes" / "global.route-shapes.runtime.json"
DEFAULT_OUTPUT = PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "diagnostics" / "2026-08-02-shared-corridor-evidence.json"

KM_PER_DEG_LAT = 110.574


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze the shared SEA/Taiwan-Japan corridor from one retained ADS-B raw date.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--corridor-radius-km", type=float, default=500.0)
    parser.add_argument("--bin-km", type=float, default=80.0)
    parser.add_argument("--cross-bin-km", type=float, default=25.0)
    args = parser.parse_args()

    parts = sorted(
        item for item in args.raw_dir.iterdir()
        if item.is_file() and item.name.endswith((".tar.aa", ".tar.ab", ".tar.ac", ".tar.ad", ".tar.ae", ".tar.af"))
    )
    if not parts:
        raise SystemExit(f"No split tar parts found in {args.raw_dir}")

    runtime = json.loads(args.runtime.read_text(encoding="utf-8"))
    route = runtime.get("routes", {}).get("KHH-NRT")
    if not route:
        raise SystemExit("KHH-NRT route is missing from the runtime route-shape pack")
    baseline = [(35.6895, 139.6917), (13.7563, 100.5018)]
    # The runtime KHH-NRT path is already KHH -> NRT; prepend BKK.
    validation_points = [(float(p[1]), float(p[2])) for p in route.get("p", []) if len(p) >= 3]
    baseline = validation_points
    baseline.insert(0, (13.7563, 100.5018))
    baseline = _dedupe_points(baseline)
    prepared_baseline = _prepare_polyline(baseline)
    baseline_length = sum(item["segmentLengthKm"] for item in prepared_baseline)
    khh = (22.577101, 120.349998)
    nrt = (35.76858, 140.388714)
    khh_projection = _project_to_polyline(khh, prepared_baseline)
    corridor_bounds = (9.0, 40.5, 85.0, 147.0)

    options = BuildOptions(min_points=8, max_trace_gap_s=2700)
    support: dict[tuple[int, int], set[int]] = defaultdict(set)
    icao_support: dict[tuple[int, int], set[str]] = defaultdict(set)
    callsign_support: dict[tuple[int, int], set[str]] = defaultdict(set)
    stats = {
        "tracesSeen": 0,
        "legsSeen": 0,
        "longForwardLegs": 0,
        "corridorCandidateLegs": 0,
        "parseErrors": 0,
    }
    leg_id = 0

    for source_name, payload in iter_trace_payloads_from_split_tar(parts):
        stats["tracesSeen"] += 1
        try:
            trace = json.loads(payload)
            points = parse_trace_points(trace)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            stats["parseErrors"] += 1
            continue
        for leg_index, leg in enumerate(split_legs(points, options)):
            stats["legsSeen"] += 1
            leg_id += 1
            if len(leg) < 8:
                continue
            distance = route_distance_km([(p.lat, p.lon) for p in leg])
            if distance < 200:
                continue
            relevant_points = [
                p for p in leg
                if corridor_bounds[0] <= p.lat <= corridor_bounds[1]
                and corridor_bounds[2] <= p.lon <= corridor_bounds[3]
            ]
            if len(relevant_points) < 6:
                continue
            projections = [_project_to_polyline((p.lat, p.lon), prepared_baseline) for p in relevant_points]
            forward_steps = sum(
                1 for previous, current in zip(projections, projections[1:], strict=False) if current["alongKm"] >= previous["alongKm"] - 20
            )
            forward_fraction = forward_steps / max(1, len(projections) - 1)
            along_values = [item["alongKm"] for item in projections]
            span = max(along_values) - min(along_values)
            if span < baseline_length * 0.06 or forward_fraction < 0.6:
                continue
            stats["longForwardLegs"] += 1
            near = [item for item in projections if abs(item["crossKm"]) <= args.corridor_radius_km]
            if len(near) < max(6, len(projections) // 5):
                continue
            stats["corridorCandidateLegs"] += 1
            callsign = _most_common_callsign(leg)
            icao = str(trace.get("icao") or "")
            touched: set[tuple[int, int]] = set()
            for item in near:
                along_bin = int(item["alongKm"] // args.bin_km)
                cross_bin = int(round(item["crossKm"] / args.cross_bin_km))
                touched.add((along_bin, cross_bin))
            for key in touched:
                support[key].add(leg_id)
                if icao:
                    icao_support[key].add(icao)
                if callsign:
                    callsign_support[key].add(callsign)

    bins = _summarize_bins(support, icao_support, callsign_support, args.bin_km, args.cross_bin_km)
    chains = _find_chains(bins, max_cross_step=2, min_support=2)
    chains_strong = _find_chains(bins, max_cross_step=2, min_support=3)
    khh_bin = int(khh_projection["alongKm"] // args.bin_km)
    nrt_bin = int(_project_to_polyline(nrt, prepared_baseline)["alongKm"] // args.bin_km)
    khh_candidates = [row for row in bins if row["alongBin"] in {khh_bin - 1, khh_bin, khh_bin + 1}]
    best_khh = min(khh_candidates, key=lambda row: abs(row["crossKm"])) if khh_candidates else None

    report = {
        "schemaVersion": 1,
        "date": "2026-08-02",
        "method": {
            "description": "Raw legs are projected onto BKK -> current KHH-NRT validation-path baseline; airport-pair labels are ignored.",
            "baseline": [{"lat": lat, "lon": lon} for lat, lon in baseline],
            "baselineLengthKm": round(baseline_length, 1),
            "corridorRadiusKm": args.corridor_radius_km,
            "alongBinKm": args.bin_km,
            "crossBinKm": args.cross_bin_km,
            "minimumLegKm": 200,
            "minimumForwardFraction": 0.6,
        },
        "stats": stats,
        "anchors": {
            "KHH": {**khh_projection, "alongBin": khh_bin},
            "NRT": {**_project_to_polyline(nrt, prepared_baseline), "alongBin": nrt_bin},
        },
        "sharedCorridorBins": bins,
        "chains": {
            "supportAtLeast2Legs": chains,
            "supportAtLeast3Legs": chains_strong,
        },
        "khhJoin": {
            "nearestSupportedBin": best_khh,
            "distanceFromKhhToNearestSupportedBinKm": round(abs(best_khh["crossKm"]), 1) if best_khh else None,
            "interpretation": (
                "corridor_near_khh_candidate"
                if best_khh and abs(best_khh["crossKm"]) <= 50
                else "no_supported_corridor_within_50km_of_khh"
            ),
        },
        "limitations": [
            "One date is evidence for a shared corridor, not proof of a complete KHH ADS-B endpoint.",
            "KHH-to-corridor remains inferred unless a raw leg enters a KHH departure/arrival envelope.",
            "The validation path is used as a search baseline, not as proof of actual flown geometry.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "stats": stats, "khhJoin": report["khhJoin"], "chains": {k: len(v) for k, v in report["chains"].items()}}, ensure_ascii=False, indent=2))
    return 0


def _summarize_bins(
    support: dict[tuple[int, int], set[int]],
    icao_support: dict[tuple[int, int], set[str]],
    callsign_support: dict[tuple[int, int], set[str]],
    bin_km: float,
    cross_bin_km: float,
) -> list[dict[str, Any]]:
    rows = []
    for (along_bin, cross_bin), leg_ids in sorted(support.items()):
        if not leg_ids:
            continue
        rows.append({
            "alongBin": along_bin,
            "alongStartKm": round(along_bin * bin_km, 1),
            "crossBin": cross_bin,
            "crossKm": round(cross_bin * cross_bin_km, 1),
            "supportLegs": len(leg_ids),
            "supportAircraft": len(icao_support[(along_bin, cross_bin)]),
            "supportCallsigns": len(callsign_support[(along_bin, cross_bin)]),
        })
    return rows


def _find_chains(bins: list[dict[str, Any]], max_cross_step: int, min_support: int) -> list[dict[str, Any]]:
    candidates = [row for row in bins if row["supportLegs"] >= min_support]
    by_along: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        by_along[row["alongBin"]].append(row)
    all_bins = sorted(by_along)
    chains: list[list[dict[str, Any]]] = []
    for start in all_bins:
        for row in sorted(by_along[start], key=lambda item: (-item["supportLegs"], abs(item["crossBin"])))[:6]:
            chain = [row]
            current = row
            for next_bin in all_bins:
                if next_bin <= current["alongBin"] or next_bin - current["alongBin"] > 2:
                    continue
                choices = [item for item in by_along[next_bin] if abs(item["crossBin"] - current["crossBin"]) <= max_cross_step]
                if not choices:
                    if next_bin - current["alongBin"] >= 2:
                        break
                    continue
                current = max(choices, key=lambda item: item["supportLegs"])
                chain.append(current)
            if len(chain) >= 3:
                chains.append(chain)
    unique: dict[tuple[int, int, int, int], list[dict[str, Any]]] = {}
    for chain in chains:
        key = (chain[0]["alongBin"], chain[-1]["alongBin"], chain[0]["crossBin"], chain[-1]["crossBin"])
        existing = unique.get(key)
        if existing is None or sum(item["supportLegs"] for item in chain) > sum(item["supportLegs"] for item in existing):
            unique[key] = chain
    result = []
    for chain in sorted(unique.values(), key=lambda items: (-(items[-1]["alongBin"] - items[0]["alongBin"]), -sum(item["supportLegs"] for item in items)))[:50]:
        result.append({
            "startAlongBin": chain[0]["alongBin"],
            "endAlongBin": chain[-1]["alongBin"],
            "coveredBins": len(chain),
            "startCrossKm": chain[0]["crossKm"],
            "endCrossKm": chain[-1]["crossKm"],
            "supportLegsSum": sum(item["supportLegs"] for item in chain),
            "bins": chain,
        })
    return result


def _prepare_polyline(polyline: list[tuple[float, float]]) -> list[dict[str, float]]:
    prepared = []
    cumulative = 0.0
    for start, end in zip(polyline, polyline[1:], strict=False):
        mean_lat = math.radians((start[0] + end[0]) / 2)
        scale_x = 111.320 * math.cos(mean_lat)
        scale_y = KM_PER_DEG_LAT
        sx, sy = start[1] * scale_x, start[0] * scale_y
        ex, ey = end[1] * scale_x, end[0] * scale_y
        dx, dy = ex - sx, ey - sy
        segment_length = haversine_km(start[0], start[1], end[0], end[1])
        prepared.append({
            "sx": sx,
            "sy": sy,
            "dx": dx,
            "dy": dy,
            "scaleX": scale_x,
            "scaleY": scale_y,
            "segmentLengthKm": segment_length,
            "cumulativeKm": cumulative,
        })
        cumulative += segment_length
    return prepared


def _project_to_polyline(point: tuple[float, float], segments: list[dict[str, float]]) -> dict[str, float]:
    lat, lon = point
    best = None
    for segment in segments:
        sx = segment["sx"]
        sy = segment["sy"]
        dx = segment["dx"]
        dy = segment["dy"]
        scale_x = segment["scaleX"]
        scale_y = segment["scaleY"]
        px, py = lon * scale_x, lat * scale_y
        denom = dx * dx + dy * dy
        ratio = 0.0 if denom == 0 else max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / denom))
        qx, qy = sx + ratio * dx, sy + ratio * dy
        distance = math.hypot(px - qx, py - qy)
        cross = ((px - sx) * dy - (py - sy) * dx) / max(1.0, math.hypot(dx, dy))
        segment_length = segment["segmentLengthKm"]
        candidate = {"alongKm": segment["cumulativeKm"] + ratio * segment_length, "crossKm": cross, "distanceKm": distance}
        if best is None or candidate["distanceKm"] < best["distanceKm"]:
            best = candidate
    return best or {"alongKm": 0.0, "crossKm": 0.0, "distanceKm": 0.0}


def _dedupe_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    output = []
    for point in points:
        if not output or point != output[-1]:
            output.append(point)
    return output


def _most_common_callsign(points: list[Any]) -> str | None:
    counts: dict[str, int] = defaultdict(int)
    for point in points:
        if point.callsign:
            counts[point.callsign] += 1
    return max(counts, key=counts.get) if counts else None


if __name__ == "__main__":
    raise SystemExit(main())
