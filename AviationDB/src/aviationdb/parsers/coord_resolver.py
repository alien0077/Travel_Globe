"""CoordinateResolver - multi-source coordinate merging.

Resolution priority:
  1. Official (AIXM / EAD / country AIP parsers)
  2. FlightGear (GPL, redistributable)
  3. X-Plane default (personal use only)
  4. OpenAIP (CC BY-NC)
  5. Inference (computed from surrounding waypoints)

Matching key: (ident, icao_region) NOT just ident.
Plus optional: FIR, nearby airway, prev/next waypoint.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aviationdb.uid import normalize_ident

EARTH_RADIUS_NM = 3440.065


@dataclass
class CoordRecord:
    ident: str
    latitude: float
    longitude: float
    source: str
    source_cycle: str = "unknown"
    confidence: int = 50
    redistributable: bool = False
    icao_region: str = ""
    fir: str = ""
    country: str = ""
    match_method: str = ""


@dataclass
class ResolvedPoint:
    ident: str
    latitude: float | None
    longitude: float | None
    source: str = ""
    confidence: int = 0
    redistributable: bool = False
    icao_region: str = ""
    fir: str = ""
    country: str = ""
    match_method: str = ""
    notes: list[str] = field(default_factory=list)


class CoordinateResolver:
    """Multi-source coordinate resolver with priority and cross-validation."""

    def __init__(self) -> None:
        self.registries: dict[str, dict[tuple[str, str], CoordRecord]] = {}
        self.results: dict[str, ResolvedPoint] = {}

    def load_json(self, source: str, json_path: Path, redistributable: bool,
                  confidence: int = 80) -> None:
        """Load a coordinate JSON file (OpenAIP/AIXM format)."""
        if not json_path.exists():
            return
        with open(json_path) as f:
            data = json.load(f)
        registry: dict[tuple[str, str], CoordRecord] = {}
        for ident, pt in data.get("points", {}).items():
            nid = normalize_ident(ident)
            if not nid:
                continue
            lat = pt.get("lat", 0)
            lon = pt.get("lon", 0)
            if lat == 0 and lon == 0:
                continue
            region = pt.get("region", "")
            key = (nid, region)
            record = CoordRecord(
                ident=nid, latitude=lat, longitude=lon,
                source=source, source_cycle=data.get("cycle", "unknown"),
                confidence=confidence, redistributable=redistributable,
                icao_region=region,
            )
            if key not in registry:
                registry[key] = record
        self.registries[source] = registry

    def load_xplane_fixes(self, source: str, fixes: dict[tuple[str, str], dict],
                          redistributable: bool, confidence: int = 80) -> None:
        """Load X-Plane/ FlightGear fix data."""
        registry: dict[tuple[str, str], CoordRecord] = {}
        for (ident, region), pt in fixes.items():
            nid = normalize_ident(ident)
            if not nid:
                continue
            key = (nid, region)
            record = CoordRecord(
                ident=nid, latitude=pt["lat"], longitude=pt["lon"],
                source=source, source_cycle=pt.get("source_cycle", "unknown"),
                confidence=confidence, redistributable=redistributable,
                icao_region=region, fir=pt.get("airport", ""),
            )
            if key not in registry:
                registry[key] = record
        self.registries[source] = registry

    def resolve(self, ident: str, icao_region: str = "",
                fir: str = "", country: str = "") -> ResolvedPoint:
        """Resolve a waypoint's coordinates from the best available source."""
        nid = normalize_ident(ident)
        result = ResolvedPoint(ident=nid, latitude=None, longitude=None,
                                icao_region=icao_region, fir=fir, country=country)

        # Priority order: official → flightgear → xplane → openaip
        source_priority = ["official", "flightgear", "xplane", "openaip", "aixm"]

        for src_name in source_priority:
            registry = self.registries.get(src_name)
            if not registry:
                continue

            candidates = []
            # Exact match on (ident, region)
            if icao_region:
                key = (nid, icao_region)
                if key in registry:
                    candidates.append(registry[key])

            # Fallback: match on ident only (but lower confidence)
            key_any = (nid, "")
            if key_any in registry and (icao_region == "" or key_any not in [c.icao_region for c in candidates]):
                record = registry[key_any]
                candidates.append(record)

            if not candidates:
                continue

            best = candidates[0]
            # Check cross-validation if we already have a result
            if result.latitude is not None:
                dist = self._haversine_nm(
                    result.latitude, result.longitude,
                    best.latitude, best.longitude
                )
                if dist < 0.1:
                    result.confidence = min(100, result.confidence + 10)
                    result.notes.append(f"{src_name}: agrees within {dist:.2f} NM")
                    result.match_method = "cross_validated"
                elif dist < 1:
                    result.notes.append(f"{src_name}: agrees within {dist:.2f} NM")
                elif dist > 50:
                    result.notes.append(f"{src_name}: DISAGREES by {dist:.1f} NM - possible duplicate ident")
                continue

            result.latitude = best.latitude
            result.longitude = best.longitude
            result.source = best.source
            result.confidence = best.confidence
            result.redistributable = best.redistributable
            result.match_method = f"{src_name}_exact"
            result.notes.append(f"from {src_name} (conf={best.confidence})")

        return result

    def bulk_resolve(self, idents: list[tuple[str, str, str, str]]) -> list[ResolvedPoint]:
        """Resolve a list of (ident, region, fir, country) tuples."""
        return [self.resolve(ident, region, fir, country)
                for ident, region, fir, country in idents]

    def _haversine_nm(self, lat1: float, lon1: float,
                      lat2: float, lon2: float) -> float:
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) *
             math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(a))
