"""AIXM 5.1 Parser - Extract DesignatedPoint and Navaid coordinates.

Parses AIXM 5.1 XML files from national AIS providers (Germany DFS, Spain ENAIRE, etc.)
and extracts DesignatedPoint and Navaid features with their geographic coordinates.
"""
from __future__ import annotations

import re
from pathlib import Path

from aviationdb.models import NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import normalize_ident

# AIXM namespaces - support both 5.1 and 5.1.1
AIXM_NS_511 = "http://www.aixm.aero/schema/5.1.1"
AIXM_NS_51 = "http://www.aixm.aero/schema/5.1"
NS = {
    "aixm": AIXM_NS_511,
    "aixm51": AIXM_NS_51,
    "gml": "http://www.opengis.net/gml/3.2",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


def _detect_ns(xml_path: Path) -> dict:
    """Detect AIXM namespace and return appropriate NS dict."""
    try:
        from lxml import etree
        tree = etree.parse(str(xml_path))
        root_tag = tree.getroot().tag
        if AIXM_NS_511 in root_tag:
            return {"aixm": AIXM_NS_511, "gml": "http://www.opengis.net/gml/3.2"}
        elif AIXM_NS_51 in root_tag:
            return {"aixm": AIXM_NS_51, "gml": "http://www.opengis.net/gml/3.2"}
    except Exception:
        pass
    return {"aixm": AIXM_NS_511, "gml": "http://www.opengis.net/gml/3.2"}

EAD_FIR = "EAD_EUROPE"


def _parse_aixm_features(xml_path: Path, feature: str, timeslice: str,
                         desig_tag: str = "designator", type_tag: str = "type") -> dict[str, tuple[float, float, str]]:
    """Generic AIXM feature parser."""
    result: dict[str, tuple[float, float, str]] = {}
    try:
        from lxml import etree
    except ImportError:
        return result
    ns = _detect_ns(xml_path)
    aixm = ns["aixm"]
    gml = ns["gml"]
    tree = etree.parse(str(xml_path))
    for el in tree.findall(f"//{{{aixm}}}{feature}"):
        ts = el.find(f".//{{{aixm}}}{timeslice}")
        if ts is None:
            continue
        desig_el = ts.find(f"{{{aixm}}}{desig_tag}")
        type_el = ts.find(f"{{{aixm}}}{type_tag}") if type_tag else None
        pos_el = ts.find(f".//{{{gml}}}pos")
        if desig_el is None or pos_el is None:
            continue
        ident = normalize_ident(desig_el.text or "")
        if not ident:
            continue
        coords = (pos_el.text or "").strip().split()
        if len(coords) < 2:
            continue
        lat, lon = float(coords[0]), float(coords[1])
        pt_type = (type_el.text or "").strip() if type_el is not None else "ICAO"
        if ident not in result:
            result[ident] = (lat, lon, pt_type)
    return result


def parse_aixm_designated_points(xml_path: Path, source_id: str) -> dict[str, tuple[float, float, str]]:
    return _parse_aixm_features(xml_path, "DesignatedPoint", "DesignatedPointTimeSlice")


def parse_aixm_navaids(xml_path: Path, source_id: str) -> dict[str, tuple[float, float, str]]:
    return _parse_aixm_features(xml_path, "Navaid", "NavaidTimeSlice")


def build_openaip_style_json(output_path: Path) -> None:
    """Build a combined OpenAIP-style JSON from all available AIXM sources."""
    import json
    from aviationdb.config import PROJECT_ROOT
    aixm_dir = PROJECT_ROOT / "data" / "raw" / "aixm"
    if not aixm_dir.exists():
        return

    all_points: dict[str, dict] = {}
    country_stats: dict[str, dict] = {}

    for country_dir in sorted(aixm_dir.iterdir()):
        if not country_dir.is_dir():
            continue
        country = country_dir.name
        country_stats[country] = {"aixm_waypoints": 0, "aixm_navaids": 0}

        def scan_xml(dir_path: Path) -> list[Path]:
            """Recursively find AIXM XML files."""
            files = []
            for f in dir_path.rglob("*.xml"):
                if f.stat().st_size > 10000:  # >10KB = real dataset
                    files.append(f)
            return files

        # Parse Designated Points from all XML files
        waypoint_count = 0
        for f in scan_xml(country_dir):
            pts = parse_aixm_designated_points(f, f"aixm_{country}")
            if len(pts) > waypoint_count:
                waypoint_count = len(pts)
            for ident, (lat, lon, pt_type) in pts.items():
                if ident not in all_points:
                    all_points[ident] = {"lat": lat, "lon": lon, "type": pt_type}
        country_stats[country]["aixm_waypoints"] = waypoint_count

        # Parse Navaids from all XML files
        navaid_count = 0
        for f in scan_xml(country_dir):
            navs = parse_aixm_navaids(f, f"aixm_{country}")
            if len(navs) > navaid_count:
                navaid_count = len(navs)
            for ident, (lat, lon, nav_type) in navs.items():
                if ident not in all_points:
                    all_points[ident] = {"lat": lat, "lon": lon, "type": nav_type}
        country_stats[country]["aixm_navaids"] = navaid_count

    if all_points:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump({
                "source": "aixm",
                "countries": country_stats,
                "total_points": len(all_points),
                "points": all_points,
            }, f, indent=2)
        print(f"AIXM coordinates saved to {output_path}")
        print(f"Total points: {len(all_points)}")
        for c, stats in sorted(country_stats.items()):
            total = stats["aixm_waypoints"] + stats["aixm_navaids"]
            if total > 0:
                print(f"  {c}: {stats['aixm_waypoints']} waypoints, {stats['aixm_navaids']} navaids")
