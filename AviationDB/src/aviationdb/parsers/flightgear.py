"""FlightGear navdata parser (X-Plane legacy format).

FlightGear uses X-Plane-compatible data files:
  - fix.dat / earth_fix.dat: waypoints
  - awy.dat / earth_awy.dat: airways
  - nav.dat / earth_nav.dat: navaids

All FlightGear core data is GPL-licensed.
"""
from __future__ import annotations

import re
from pathlib import Path

from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

REDISTRIBUTABLE = True
SOURCE_PREFIX = "flightgear"
FIR_DEFAULT = "FG_GLOBAL"
COUNTRY_DEFAULT = "XX"
REGION_CODE = "global"

# Row codes for nav.dat
NAV_TYPE_MAP = {
    2: "NDB",
    3: "VOR",
    4: "ILS",
    5: "LOCALIZER",
    6: "GLIDESLOPE",
    7: "OM",
    8: "MM",
    9: "IM",
    12: "DME",
    13: "DME",
}


def _parse_header(lines: list[str]) -> dict:
    """Parse FlightGear/X-Plane data file header."""
    info = {"version": "unknown", "cycle": "unknown", "build": "unknown"}
    for line in lines[:5]:
        line = line.strip()
        if line.startswith("I") or line.startswith("A"):
            parts = line.split()
            if len(parts) >= 2:
                info["version"] = parts[1]
            # Try to extract AIRAC cycle
            m = re.search(r"cycle\s*(\d{4})", line, re.I)
            if m:
                info["cycle"] = m.group(1)
            m = re.search(r"build\s*(\d{8})", line, re.I)
            if m:
                info["build"] = m.group(1)
    return info


def parse_fix_dat(filepath: Path, source_id: str) -> dict[str, dict]:
    """Parse fix.dat format (legacy X-Plane 600/700/810 format).
    
    Line format:  lat   lon   ident
    Where ident is 5 characters, lat/lon in decimal degrees.
    Also supports newer 1100/1200 format:
      lat   lon   ident   airport_icao  region_code [type] [name]
    """
    result: dict[str, dict] = {}
    text = filepath.read_text(encoding="utf-8", errors="replace")
    header = _parse_header(text.split("\n"))
    lines = text.split("\n")

    # Detect format: check a data line (skip header)
    sample_line = ""
    for line in lines:
        s = line.strip()
        if not s or s.startswith(("I", "A")) or s == "99":
            continue
        parts = s.split()
        if len(parts) >= 3:
            sample_line = s
            break

    is_new_format = len(sample_line.split()) >= 5 if sample_line else False

    for line in lines:
        s = line.strip()
        if not s or s.startswith(("I", "A")) or s == "99":
            continue
        parts = s.split()
        if len(parts) < 3:
            continue
        try:
            lat = float(parts[0])
            lon = float(parts[1])
        except ValueError:
            continue
        if abs(lat) > 90 or abs(lon) > 180:
            continue
        ident = normalize_ident(parts[2])
        if not ident or len(ident) < 2:
            continue

        region = parts[4] if is_new_format and len(parts) > 4 else "XX"
        airport = parts[3] if is_new_format and len(parts) > 3 else "ENRT"
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


def parse_nav_dat(filepath: Path, source_id: str) -> dict[str, dict]:
    """Parse earth_nav.dat / nav.dat format.
    
    Row codes: 2=NDB, 3=VOR, 4/5=LOC, 6=GS, 12/13=DME
    """
    result: dict[str, dict] = {}
    text = filepath.read_text(encoding="utf-8", errors="replace")
    header = _parse_header(text.split("\n"))

    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("I") or line.startswith("A") or line == "99":
            continue
        parts = line.split()
        if len(parts) < 8:
            continue
        try:
            row_code = int(parts[0])
        except ValueError:
            continue
        if row_code not in (2, 3, 12, 13):
            continue

        try:
            lat = float(parts[1])
            lon = float(parts[2])
        except ValueError:
            continue

        # ident is at different positions depending on row code
        if row_code in (2, 3):
            ident = normalize_ident(parts[7]) if len(parts) > 7 else ""
        elif row_code in (12, 13):
            ident = normalize_ident(parts[7]) if len(parts) > 7 else ""
        else:
            continue

        if not ident:
            continue

        region = parts[9] if len(parts) > 9 else "XX"
        nav_type = NAV_TYPE_MAP.get(row_code, "NAVAID")
        key = (ident, region)
        if key not in result:
            result[key] = {
                "ident": ident,
                "lat": lat,
                "lon": lon,
                "region": region,
                "airport": "ENRT",
                "type": nav_type,
                "source": source_id,
                "source_cycle": header["cycle"],
                "redistributable": REDISTRIBUTABLE,
            }
    return result


def parse_awy_dat(filepath: Path, source_id: str) -> list[dict]:
    """Parse awy.dat / earth_awy.dat format.
    
    Format: from_ident from_lat from_lon to_ident to_lat to_lon level base top route_name
    Level: 1=low, 2=high
    Base/Top: hundreds of feet MSL
    """
    segments: list[dict] = []
    text = filepath.read_text(encoding="latin-1", errors="replace")
    
    for line in text.split("\n"):
        s = line.strip()
        if not s or s.startswith(("I", "A")) or s == "99":
            continue
        parts = s.split()
        if len(parts) < 10:
            continue
        # Skip header-ish lines
        if not parts[0][0].isalpha() or not parts[6].isdigit():
            continue
        try:
            from_lat, from_lon = float(parts[1]), float(parts[2])
            to_lat, to_lon = float(parts[4]), float(parts[5])
        except ValueError:
            continue
        from_ident = normalize_ident(parts[0])
        to_ident = normalize_ident(parts[3])
        if not from_ident or not to_ident:
            continue
        level = int(parts[6])
        base_ft = int(parts[7]) * 100
        top_ft = int(parts[8]) * 100
        
        # Route name might be multiple names separated by spaces/hyphens
        route = normalize_ident(parts[9]) if len(parts) > 9 else ""
        if not route:
            continue
            
        segments.append({
            "from_ident": from_ident, "from_lat": from_lat, "from_lon": from_lon,
            "to_ident": to_ident, "to_lat": to_lat, "to_lon": to_lon,
            "level": level, "base_ft": base_ft, "top_ft": top_ft,
            "route": route, "source": source_id,
        })
    return segments


def parse_databases(source_id: str = "flightgear") -> dict:
    """Scan for FlightGear data files in data/raw/flightgear/.
    
    Returns: {"points": {(ident,region): {...}}, "airways": [{...}]}
    """
    from aviationdb.config import PROJECT_ROOT

    base_dir = PROJECT_ROOT / "data" / "raw" / "flightgear"
    if not base_dir.exists():
        return {"points": {}, "airways": []}

    all_points: dict[tuple[str, str], dict] = {}
    all_airways: list[dict] = []

    # Parse fix.dat / earth_fix.dat
    for pattern in ["*fix*", "*FIX*"]:
        for f in sorted(base_dir.rglob(pattern)):
            if f.suffix not in (".dat", ".txt") or f.name.startswith("."):
                continue
            pts = parse_fix_dat(f, source_id)
            all_points.update(pts)

    # Parse nav.dat / earth_nav.dat
    for pattern in ["*nav*", "*NAV*"]:
        for f in sorted(base_dir.rglob(pattern)):
            if f.suffix not in (".dat", ".txt") or f.name.startswith("."):
                continue
            pts = parse_nav_dat(f, source_id)
            all_points.update(pts)

    # Parse awy.dat / earth_awy.dat
    for pattern in ["*awy*", "*AWY*"]:
        for f in sorted(base_dir.rglob(pattern)):
            if f.suffix not in (".dat", ".txt") or f.name.startswith("."):
                continue
            segs = parse_awy_dat(f, source_id)
            all_airways.extend(segs)

    return {"points": all_points, "airways": all_airways}
