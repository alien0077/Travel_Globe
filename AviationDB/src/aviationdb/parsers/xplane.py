"""X-Plane 11/12 navdata parser.

X-Plane default data files (Resources/default data/):
  - earth_fix.dat: waypoints (XP FIX1101/FIX1200)
  - earth_awy.dat: airways (XP AWY1101)
  - earth_nav.dat: navaids (XP NAV1150/NAV1200)

X-Plane data is for personal use only - NOT redistributable.
"""
from __future__ import annotations

import re
from pathlib import Path

from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

REDISTRIBUTABLE = False
SOURCE_PREFIX = "xplane"
FIR_DEFAULT = "XP_GLOBAL"
COUNTRY_DEFAULT = "XX"
REGION_CODE = "global"

# Nav types from row codes
NAV_TYPES = {2: "NDB", 3: "VOR", 4: "ILS", 5: "LOCALIZER",
             6: "GLIDESLOPE", 7: "OM", 8: "MM", 9: "IM",
             12: "DME", 13: "DME"}

# AWY fix/navaid type: 11=fix, 2=NDB, 3=VHF navaid
FIX_TYPE_MAP = {11: "SIGNIFICANT_POINT", 2: "NDB", 3: "VOR"}


def _parse_header(lines: list[str]) -> dict:
    info = {"version": "unknown", "cycle": "unknown", "build": "unknown"}
    for line in lines[:5]:
        s = line.strip()
        if s.startswith("I") or s.startswith("A"):
            parts = s.split()
            if len(parts) >= 2:
                info["version"] = parts[1]
            m = re.search(r"cycle\s*(\d{4})", s, re.I)
            if m:
                info["cycle"] = m.group(1)
            m = re.search(r"build\s*(\d{8})", s, re.I)
            if m:
                info["build"] = m.group(1)
    return info


def parse_fix_dat(filepath: Path, source_id: str) -> dict[tuple[str, str], dict]:
    """Parse X-Plane earth_fix.dat."""
    result: dict[tuple[str, str], dict] = {}
    text = filepath.read_text(encoding="utf-8", errors="replace")
    header = _parse_header(text.split("\n"))

    for line in text.split("\n"):
        s = line.strip()
        if not s or s.startswith(("I", "A")) or s == "99":
            continue
        parts = s.split()
        if len(parts) < 5:
            continue
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        ident = normalize_ident(parts[2])
        if not ident:
            continue
        airport = parts[3]
        region = parts[4]
        key = (ident, region)
        if key not in result:
            result[key] = {
                "ident": ident, "lat": lat, "lon": lon,
                "region": region, "airport": airport,
                "type": "SIGNIFICANT_POINT",
                "source": source_id, "source_cycle": header["cycle"],
                "redistributable": REDISTRIBUTABLE,
            }
    return result


def parse_nav_dat(filepath: Path, source_id: str) -> dict[tuple[str, str], dict]:
    """Parse X-Plane earth_nav.dat."""
    result: dict[tuple[str, str], dict] = {}
    text = filepath.read_text(encoding="utf-8", errors="replace")
    header = _parse_header(text.split("\n"))

    for line in text.split("\n"):
        s = line.strip()
        if not s or s.startswith(("I", "A")) or s == "99":
            continue
        parts = s.split()
        if len(parts) < 8:
            continue
        try:
            row_code = int(parts[0])
        except ValueError:
            continue
        if row_code not in (2, 3, 12, 13):
            continue
        try:
            lat, lon = float(parts[1]), float(parts[2])
        except ValueError:
            continue
        # Ident position: nav format v1100/v1200
        ident = normalize_ident(parts[7]) if len(parts) > 7 else ""
        if not ident:
            continue
        region = parts[9] if len(parts) > 9 else "XX"
        nav_type = NAV_TYPES.get(row_code, "NAVAID")
        key = (ident, region)
        if key not in result:
            result[key] = {
                "ident": ident, "lat": lat, "lon": lon,
                "region": region, "airport": "ENRT",
                "type": nav_type,
                "source": source_id, "source_cycle": header["cycle"],
                "redistributable": REDISTRIBUTABLE,
            }
    return result


def parse_awy_dat(filepath: Path, source_id: str) -> list[dict]:
    """Parse X-Plane earth_awy.dat."""
    segments: list[dict] = []
    text = filepath.read_text(encoding="utf-8", errors="replace")
    _parse_header(text.split("\n"))

    for line in text.split("\n"):
        s = line.strip()
        if not s or s.startswith(("I", "A")) or s == "99":
            continue
        parts = s.split()
        if len(parts) < 10:
            continue
        from_fix = normalize_ident(parts[0])
        from_region = parts[1]
        from_type = int(parts[2])
        to_fix = normalize_ident(parts[3])
        to_region = parts[4]
        to_type = int(parts[5])
        direction = parts[6] if len(parts) > 6 else "N"
        level = int(parts[7]) if len(parts) > 7 else 1
        base_ft = int(parts[8]) if len(parts) > 8 else 0
        top_ft = int(parts[9]) if len(parts) > 9 else 0
        designator = normalize_ident(parts[10]) if len(parts) > 10 else ""

        if not from_fix or not to_fix or not designator:
            continue

        segments.append({
            "designator": designator,
            "from_ident": from_fix, "from_region": from_region, "from_type": from_type,
            "to_ident": to_fix, "to_region": to_region, "to_type": to_type,
            "direction": direction, "level": level,
            "base_ft": base_ft, "top_ft": top_ft,
            "source": source_id,
        })
    return segments


def scan_databases(source_id: str = "xplane") -> dict:
    """Scan for X-Plane data files in data/raw/xplane/."""
    from aviationdb.config import PROJECT_ROOT

    base_dir = PROJECT_ROOT / "data" / "raw" / "xplane"
    if not base_dir.exists():
        return {"fixes": {}, "navaids": {}, "airways": []}

    result: dict = {"fixes": {}, "navaids": {}, "airways": []}

    for pattern in ["*fix*", "*FIX*"]:
        for f in sorted(base_dir.rglob(pattern)):
            if f.suffix not in (".dat", ".txt") or f.name.startswith("."):
                continue
            if "awy" in f.name.lower() or "nav" in f.name.lower():
                continue
            pts = parse_fix_dat(f, source_id)
            result["fixes"].update(pts)

    for pattern in ["*nav*", "*NAV*"]:
        for f in sorted(base_dir.rglob(pattern)):
            if f.suffix not in (".dat", ".txt") or f.name.startswith("."):
                continue
            if "awy" in f.name.lower() or "fix" in f.name.lower():
                continue
            pts = parse_nav_dat(f, source_id)
            result["navaids"].update(pts)

    for pattern in ["*awy*", "*AWY*"]:
        for f in sorted(base_dir.rglob(pattern)):
            if f.suffix not in (".dat", ".txt") or f.name.startswith("."):
                continue
            segs = parse_awy_dat(f, source_id)
            result["airways"].extend(segs)

    return result
