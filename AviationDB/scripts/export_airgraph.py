#!/usr/bin/env python3
"""Export global Airgraph Pack directly from FlightGear awy.dat.

Produces a single JSON file with ONLY the main connected component.
Compatible with replay-engine's AirgraphPack format.

Usage:
  python scripts/export_airgraph.py
"""
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT / "data" / "raw" / "flightgear"


def main() -> int:
    awy_path = RAW_DIR / "awy.dat"
    if not awy_path.exists():
        print(f"❌ awy.dat not found: {awy_path}")
        return 1

    print("Parsing awy.dat...")
    waypoint_key_to_idx: dict[tuple[str, float, float], int] = {}
    waypoints: list[list] = []
    airways: dict[str, int] = {}
    airway_list: list[list] = []
    segments_raw: list[tuple[int, int, int, float, str]] = []
    seg_count: dict[str, int] = defaultdict(int)

    with open(awy_path, encoding="latin-1") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith(("I", "A")) or s == "99":
                continue
            parts = s.split()
            if len(parts) < 10 or not parts[0][0].isalpha() or not parts[6].isdigit():
                continue
            try:
                from_lat, from_lon = float(parts[1]), float(parts[2])
                to_lat, to_lon = float(parts[4]), float(parts[5])
            except ValueError:
                continue

            route = parts[9]
            if not route:
                continue

            from_ident, to_ident = parts[0], parts[3]

            def _register(ident: str, lat: float, lon: float) -> int:
                key = (ident, round(lat, 5), round(lon, 5))
                idx = waypoint_key_to_idx.get(key)
                if idx is None:
                    idx = len(waypoints)
                    waypoint_key_to_idx[key] = idx
                    waypoints.append([ident, round(lat, 6), round(lon, 6), "SIGNIFICANT_POINT", "flightgear"])
                return idx

            from_idx = _register(from_ident, from_lat, from_lon)
            to_idx = _register(to_ident, to_lat, to_lon)

            if route not in airways:
                airways[route] = len(airway_list)
                airway_list.append([route, "ATS", "flightgear"])

            seg_count[route] += 1
            dlat = math.radians(to_lat - from_lat)
            dlon = math.radians(to_lon - from_lon)
            a = (math.sin(dlat / 2) ** 2 +
                 math.cos(math.radians(from_lat)) *
                 math.cos(math.radians(to_lat)) *
                 math.sin(dlon / 2) ** 2)
            dist_nm = round(2 * 3440.065 * math.asin(min(1, math.sqrt(a))), 2)

            segments_raw.append((from_idx, to_idx, airways[route], dist_nm, ""))

    print(f"  Total waypoints: {len(waypoints):,}")
    print(f"  Total airways:   {len(airway_list):,}")
    print(f"  Total segments:  {len(segments_raw):,}")

    # Find main connected component
    print("\nComputing connected components...")
    adj: dict[int, set[int]] = defaultdict(set)
    all_pts: set[int] = set()
    for f, t, *_ in segments_raw:
        adj[f].add(t)
        adj[t].add(f)
        all_pts.add(f)
        all_pts.add(t)

    visited: set[int] = set()
    components: list[set[int]] = []
    for i in all_pts:
        if i in visited:
            continue
        stack = [i]
        comp: set[int] = set()
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            comp.add(n)
            for nb in adj[n]:
                if nb not in visited:
                    stack.append(nb)
        components.append(comp)

    components.sort(key=len, reverse=True)
    main_comp = components[0]
    print(f"  Components: {len(components):,}")
    print(f"  Main graph: {len(main_comp):,} waypoints ({len(main_comp)/len(all_pts)*100:.0f}% of total)")

    # Filter: only main component
    comp_segs = [s for s in segments_raw if s[0] in main_comp and s[1] in main_comp]

    # Remap indices
    old_to_new = {old: i for i, old in enumerate(sorted(main_comp))}
    main_points = [waypoints[i] for i in sorted(main_comp)]
    remapped_segs = [[old_to_new[f], old_to_new[t], a, d, dr] for f, t, a, d, dr in comp_segs]

    awy_ids_in_comp = set(s[2] for s in remapped_segs)
    main_airways = [aw for i, aw in enumerate(airway_list) if i in awy_ids_in_comp]

    print(f"\n  Pack includes:")
    print(f"    Points:   {len(main_points):,}")
    print(f"    Airways:  {len(main_airways):,}")
    print(f"    Segments: {len(remapped_segs):,}")

    pack = {
        "schemaVersion": 1,
        "region": "global",
        "airports": [],
        "points": main_points,
        "airways": main_airways,
        "segments": remapped_segs,
    }

    # Write
    out_dir = PROJECT / "data" / "releases" / "airgraph"
    out_dir.mkdir(parents=True, exist_ok=True)
    shared_dir = PROJECT.parent / "shared" / "offline-packs" / "aviation" / "regions"
    shared_dir.mkdir(parents=True, exist_ok=True)

    raw = json.dumps(pack, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    gz = gzip.compress(raw)

    (out_dir / "global.airgraph.json").write_bytes(raw)
    (out_dir / "global.airgraph.json.gz").write_bytes(gz)
    (shared_dir / "global.airgraph.json").write_bytes(raw)
    (shared_dir / "global.airgraph.json.gz").write_bytes(gz)

    print(f"\n✅ Done!  JSON: {len(raw)/1024/1024:.1f} MB, GZIP: {len(gz)/1024/1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
