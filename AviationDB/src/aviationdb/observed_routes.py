from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import re
import sys
import tarfile
import zlib
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.request import urlopen

EARTH_RADIUS_KM = 6371.0088
ADSBLOL_RELEASES_URL = "https://raw.githubusercontent.com/adsblol/globe_history_{year}/main/PREFERRED_RELEASES.txt"


@dataclass(frozen=True)
class Airport:
    iata: str
    icao: str
    name: str
    airport_type: str
    lat: float
    lon: float


@dataclass(frozen=True)
class NearestAirport:
    airport: Airport
    distance_km: float


class AirportIndex:
    def __init__(self, airports: Iterable[Airport], cell_degrees: float = 2.0) -> None:
        self.airports = list(airports)
        self.cell_degrees = cell_degrees
        self._grid: dict[tuple[int, int], list[Airport]] = defaultdict(list)
        for airport in self.airports:
            self._grid[self._cell(airport.lat, airport.lon)].append(airport)

    @classmethod
    def from_json(cls, path: Path) -> AirportIndex:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        items = payload.get("airports", payload if isinstance(payload, list) else [])
        airports: list[Airport] = []
        for item in items:
            if not item.get("iataCode") or not item.get("icaoCode"):
                continue
            if not item.get("scheduledService"):
                continue
            if item.get("type") not in {"large_airport", "medium_airport", "small_airport"}:
                continue
            lat = item.get("latitude")
            lon = item.get("longitude")
            if lat is None or lon is None:
                continue
            airports.append(
                Airport(
                    iata=str(item["iataCode"]).upper(),
                    icao=str(item["icaoCode"]).upper(),
                    name=str(item.get("name") or item["iataCode"]),
                    airport_type=str(item.get("type") or ""),
                    lat=float(lat),
                    lon=float(lon),
                )
            )
        return cls(airports)

    def nearest(self, lat: float, lon: float, max_km: float) -> NearestAirport | None:
        cell_lat, cell_lon = self._cell(lat, lon)
        cell_radius = max(1, math.ceil(max_km / 111 / self.cell_degrees) + 1)
        best: NearestAirport | None = None
        for y in range(cell_lat - cell_radius, cell_lat + cell_radius + 1):
            for x in range(cell_lon - cell_radius, cell_lon + cell_radius + 1):
                for airport in self._grid.get((y, x), []):
                    distance = haversine_km(lat, lon, airport.lat, airport.lon)
                    if distance <= max_km and (best is None or distance < best.distance_km):
                        best = NearestAirport(airport, distance)
        return best

    def _cell(self, lat: float, lon: float) -> tuple[int, int]:
        return (math.floor(lat / self.cell_degrees), math.floor(lon / self.cell_degrees))


@dataclass(frozen=True)
class TracePoint:
    elapsed_s: float
    lat: float
    lon: float
    altitude_ft: float | None
    ground_speed_kt: float | None
    track_deg: float | None
    flags: int
    callsign: str | None


@dataclass(frozen=True)
class ObservedRouteSample:
    origin: NearestAirport
    destination: NearestAirport
    points: list[tuple[float, float]]
    distance_km: float
    callsign: str | None
    icao24: str | None
    start_timestamp: float | None
    source_file: str | None

    @property
    def route_key(self) -> str:
        return f"{self.origin.airport.iata}-{self.destination.airport.iata}"


@dataclass
class ObservedVariant:
    signature: str
    sample_count: int = 0
    distance_sum_km: float = 0
    representative_points: list[tuple[float, float]] = field(default_factory=list)
    representative_distance_km: float = 0
    example_flights: set[str] = field(default_factory=set)
    source_files: set[str] = field(default_factory=set)
    start_dates: list[str] = field(default_factory=list)

    def add(self, sample: ObservedRouteSample) -> None:
        self.sample_count += 1
        self.distance_sum_km += sample.distance_km
        mean = self.distance_sum_km / self.sample_count
        current_delta = abs(self.representative_distance_km - mean) if self.representative_points else math.inf
        new_delta = abs(sample.distance_km - mean)
        if new_delta <= current_delta:
            self.representative_points = sample.points
            self.representative_distance_km = sample.distance_km
        if sample.callsign:
            self.example_flights.add(sample.callsign)
        if sample.source_file:
            self.source_files.add(sample.source_file)
        if sample.start_timestamp:
            self.start_dates.append(datetime.fromtimestamp(sample.start_timestamp, UTC).date().isoformat())


@dataclass
class ObservedRouteGroup:
    route_key: str
    origin: Airport
    destination: Airport
    variants: dict[str, ObservedVariant] = field(default_factory=dict)

    def add(self, sample: ObservedRouteSample, signature: str) -> None:
        variant = self.variants.setdefault(signature, ObservedVariant(signature=signature))
        variant.add(sample)

    @property
    def sample_count(self) -> int:
        return sum(variant.sample_count for variant in self.variants.values())

    def best_variant(self) -> ObservedVariant:
        return max(self.variants.values(), key=lambda item: item.sample_count)


@dataclass(frozen=True)
class BuildOptions:
    min_points: int = 8
    min_route_km: float = 120
    max_airport_km: float = 150
    max_trace_gap_s: float = 2700
    simplify_tolerance_km: float = 8
    max_points_per_route: int = 96
    signature_samples: int = 14
    signature_quantum_deg: float = 0.5
    max_track_detour_ratio: float = 2.6
    limit_traces: int | None = None


@dataclass(frozen=True)
class BuildStats:
    traces_seen: int
    traces_parsed: int
    legs_seen: int
    samples_accepted: int
    samples_rejected: int


@dataclass(frozen=True)
class ReleaseEntry:
    date: str
    urls: list[str]


class ConcatenatedBinaryIO(io.RawIOBase):
    def __init__(self, paths: list[Path]) -> None:
        self.paths = paths
        self._index = 0
        self._current: BinaryIO | None = None

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int:
        view = memoryview(buffer)
        total = 0
        while total < len(view):
            if self._current is None:
                if self._index >= len(self.paths):
                    return total
                self._current = self.paths[self._index].open("rb")
                self._index += 1
            count = self._current.readinto(view[total:])
            if count is None:
                count = 0
            if count == 0:
                self._current.close()
                self._current = None
                continue
            total += count
        return total

    def close(self) -> None:
        if self._current is not None:
            self._current.close()
            self._current = None
        super().close()


class ConcatenatedUrlBinaryIO(io.RawIOBase):
    def __init__(self, urls: list[str], timeout_s: float = 60) -> None:
        self.urls = urls
        self.timeout_s = timeout_s
        self._index = 0
        self._current: Any | None = None
        self._current_url = ""
        self._bytes_read = 0
        self._next_report = 256 * 1024 * 1024

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int:
        view = memoryview(buffer)
        total = 0
        while total < len(view):
            if self._current is None:
                if self._index >= len(self.urls):
                    return total
                self._current_url = self.urls[self._index]
                self._bytes_read = 0
                self._next_report = 256 * 1024 * 1024
                print(
                    f"opening asset {self._index + 1}/{len(self.urls)}: {self._current_url}",
                    file=sys.stderr,
                    flush=True,
                )
                self._current = urlopen(self._current_url, timeout=self.timeout_s)
                self._index += 1
            chunk = self._current.read(len(view) - total)
            if not chunk:
                print(
                    f"asset done: {self._bytes_read / 1024 / 1024:.1f} MiB",
                    file=sys.stderr,
                    flush=True,
                )
                self._current.close()
                self._current = None
                continue
            view[total : total + len(chunk)] = chunk
            total += len(chunk)
            self._bytes_read += len(chunk)
            if self._bytes_read >= self._next_report:
                print(
                    f"downloaded {self._bytes_read / 1024 / 1024:.0f} MiB from current asset",
                    file=sys.stderr,
                    flush=True,
                )
                self._next_report += 256 * 1024 * 1024
        return total

    def close(self) -> None:
        if self._current is not None:
            self._current.close()
            self._current = None
        super().close()


def build_observed_routes(
    inputs: Iterable[Path],
    airport_index: AirportIndex,
    options: BuildOptions | None = None,
) -> tuple[dict[str, ObservedRouteGroup], BuildStats]:
    options = options or BuildOptions()
    return build_observed_routes_from_payloads(iter_trace_payloads(inputs), airport_index, options)


def build_observed_routes_from_payloads(
    payloads: Iterable[tuple[str, bytes]],
    airport_index: AirportIndex,
    options: BuildOptions | None = None,
) -> tuple[dict[str, ObservedRouteGroup], BuildStats]:
    options = options or BuildOptions()
    groups: dict[str, ObservedRouteGroup] = {}
    traces_seen = 0
    traces_parsed = 0
    legs_seen = 0
    samples_accepted = 0
    samples_rejected = 0

    for source_name, payload in payloads:
        traces_seen += 1
        if options.limit_traces is not None and traces_seen > options.limit_traces:
            break
        try:
            trace = json.loads(payload)
            points = parse_trace_points(trace)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            samples_rejected += 1
            continue
        traces_parsed += 1
        for leg in split_legs(points, options):
            legs_seen += 1
            sample = sample_from_leg(
                leg=leg,
                airport_index=airport_index,
                options=options,
                icao24=trace.get("icao"),
                start_timestamp=_trace_timestamp(trace, leg),
                source_file=source_name,
            )
            if sample is None:
                samples_rejected += 1
                continue
            signature = route_signature(sample.points, options)
            group = groups.setdefault(
                sample.route_key,
                ObservedRouteGroup(
                    route_key=sample.route_key,
                    origin=sample.origin.airport,
                    destination=sample.destination.airport,
                ),
            )
            group.add(sample, signature)
            samples_accepted += 1

    return groups, BuildStats(
        traces_seen=traces_seen,
        traces_parsed=traces_parsed,
        legs_seen=legs_seen,
        samples_accepted=samples_accepted,
        samples_rejected=samples_rejected,
    )


def iter_trace_payloads(inputs: Iterable[Path]) -> Iterable[tuple[str, bytes]]:
    for path in inputs:
        if path.is_dir():
            yield from _iter_trace_payloads_from_dir(path)
        elif _looks_like_tar(path):
            yield from _iter_trace_payloads_from_tar(path)
        else:
            payload = _read_trace_file(path)
            if payload is not None:
                yield str(path), payload


def iter_trace_payloads_from_split_tar(paths: list[Path]) -> Iterable[tuple[str, bytes]]:
    with ConcatenatedBinaryIO(paths) as raw:
        buffered = io.BufferedReader(raw, buffer_size=1024 * 1024)
        yield from _iter_trace_payloads_from_tarfile(buffered, label="+".join(path.name for path in paths[:2]))


def iter_trace_payloads_from_split_urls(urls: list[str]) -> Iterable[tuple[str, bytes]]:
    with ConcatenatedUrlBinaryIO(urls) as raw:
        buffered = io.BufferedReader(raw, buffer_size=1024 * 1024)
        label = "+".join(url.rstrip("/").split("/")[-1] for url in urls[:2])
        yield from _iter_trace_payloads_from_tarfile(buffered, label=label)


def parse_trace_points(trace: dict[str, Any]) -> list[TracePoint]:
    points: list[TracePoint] = []
    for row in trace.get("trace") or []:
        if not isinstance(row, list) or len(row) < 3:
            continue
        lat = _maybe_float(row[1])
        lon = _maybe_float(row[2])
        if lat is None or lon is None:
            continue
        aircraft = row[8] if len(row) > 8 and isinstance(row[8], dict) else {}
        callsign = _clean_callsign(aircraft.get("flight") or aircraft.get("callsign") or trace.get("flight"))
        points.append(
            TracePoint(
                elapsed_s=float(row[0] or 0),
                lat=lat,
                lon=lon,
                altitude_ft=_altitude_ft(row[3] if len(row) > 3 else None),
                ground_speed_kt=_maybe_float(row[4] if len(row) > 4 else None),
                track_deg=_maybe_float(row[5] if len(row) > 5 else None),
                flags=int(row[6] or 0) if len(row) > 6 and row[6] is not None else 0,
                callsign=callsign,
            )
        )
    points.sort(key=lambda point: point.elapsed_s)
    return points


def split_legs(points: list[TracePoint], options: BuildOptions) -> list[list[TracePoint]]:
    legs: list[list[TracePoint]] = []
    current: list[TracePoint] = []
    previous: TracePoint | None = None
    for point in points:
        starts_new_leg = bool(point.flags & 2)
        gap_s = point.elapsed_s - previous.elapsed_s if previous is not None else 0
        too_sparse = previous is not None and gap_s > options.max_trace_gap_s
        jump_km = haversine_km(previous.lat, previous.lon, point.lat, point.lon) if previous is not None else 0
        jump_speed_kmh = jump_km / (gap_s / 3600) if gap_s > 0 else 0
        impossible_jump = previous is not None and gap_s <= 1200 and jump_speed_kmh > 1800
        if current and (starts_new_leg or too_sparse or impossible_jump):
            if len(current) >= options.min_points:
                legs.append(current)
            current = []
        current.append(point)
        previous = point
    if len(current) >= options.min_points:
        legs.append(current)
    return legs


def sample_from_leg(
    leg: list[TracePoint],
    airport_index: AirportIndex,
    options: BuildOptions,
    icao24: str | None,
    start_timestamp: float | None,
    source_file: str | None,
) -> ObservedRouteSample | None:
    if len(leg) < options.min_points:
        return None
    first = leg[0]
    last = leg[-1]
    origin = airport_index.nearest(first.lat, first.lon, options.max_airport_km)
    destination = airport_index.nearest(last.lat, last.lon, options.max_airport_km)
    if origin is None or destination is None or origin.airport.iata == destination.airport.iata:
        return None
    raw_points = [(point.lat, point.lon) for point in leg]
    distance = route_distance_km(raw_points)
    direct = haversine_km(origin.airport.lat, origin.airport.lon, destination.airport.lat, destination.airport.lon)
    if direct < options.min_route_km or distance < options.min_route_km:
        return None
    if direct > 0 and distance / direct > options.max_track_detour_ratio:
        return None
    simplified = simplify_route(raw_points, options.simplify_tolerance_km, options.max_points_per_route)
    callsign = _most_common_callsign(leg)
    return ObservedRouteSample(
        origin=origin,
        destination=destination,
        points=simplified,
        distance_km=round(distance, 1),
        callsign=callsign,
        icao24=icao24,
        start_timestamp=start_timestamp,
        source_file=source_file,
    )


def route_signature(points: list[tuple[float, float]], options: BuildOptions) -> str:
    sampled = resample_route(points, options.signature_samples)
    parts = []
    quantum = options.signature_quantum_deg
    for lat, lon in sampled:
        qlat = round(round(lat / quantum) * quantum, 3)
        qlon = round(round(lon / quantum) * quantum, 3)
        parts.append(f"{qlat:.3f},{qlon:.3f}")
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"q{quantum:g}:{digest}"


def groups_to_payload(
    groups: dict[str, ObservedRouteGroup],
    stats: BuildStats,
    source_urls: list[str],
    build_options: BuildOptions,
) -> dict[str, Any]:
    routes = []
    for route_key in sorted(groups):
        group = groups[route_key]
        best = group.best_variant()
        variants = sorted(group.variants.values(), key=lambda item: item.sample_count, reverse=True)
        routes.append(
            {
                "id": route_key.lower(),
                "originIata": group.origin.iata,
                "originIcao": group.origin.icao,
                "originName": group.origin.name,
                "destinationIata": group.destination.iata,
                "destinationIcao": group.destination.icao,
                "destinationName": group.destination.name,
                "sampleCount": group.sample_count,
                "variantCount": len(variants),
                "representative": _variant_payload(best, include_sources=False),
                "variants": [_variant_payload(variant, include_sources=True) for variant in variants[:6]],
            }
        )
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "source": {
            "provider": "ADSB.lol globe_history",
            "license": "ODbL-1.0",
            "licenseUrl": "https://opendatacommons.org/licenses/odbl/1-0/",
            "releaseUrls": source_urls,
        },
        "buildOptions": build_options.__dict__,
        "stats": stats.__dict__,
        "routes": routes,
    }


def write_payload(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if output.suffix == ".gz":
        output.write_bytes(gzip.compress(raw, compresslevel=9))
    else:
        output.write_bytes(raw)


def parse_preferred_releases(text: str) -> dict[str, ReleaseEntry]:
    entries: dict[str, ReleaseEntry] = {}
    for line in text.splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue
        parts = [part.strip() for part in clean.split(",") if part.strip()]
        urls = [part for part in parts if part.startswith("http")]
        date = _normalize_release_date(parts[0]) if parts else None
        if date is None:
            for url in urls:
                date = _normalize_release_date(url)
                if date:
                    break
        if date and urls:
            entries[date] = ReleaseEntry(date=date, urls=urls)
    return entries


def fetch_preferred_releases(year: int) -> dict[str, ReleaseEntry]:
    url = ADSBLOL_RELEASES_URL.format(year=year)
    with urlopen(url, timeout=60) as response:
        return parse_preferred_releases(response.read().decode("utf-8"))


def download_release(entry: ReleaseEntry, raw_dir: Path) -> list[Path]:
    release_dir = raw_dir / entry.date
    release_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for url in entry.urls:
        name = url.rstrip("/").split("/")[-1]
        target = release_dir / name
        if not target.exists() or target.stat().st_size == 0:
            partial = target.with_suffix(target.suffix + ".part")
            with urlopen(url, timeout=60) as response, partial.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            partial.replace(target)
        paths.append(target)
    return paths


def release_parts_from_dir(path: Path) -> list[Path]:
    return sorted(item for item in path.iterdir() if item.is_file() and _looks_like_tar_part(item))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(min(1, math.sqrt(a)))


def route_distance_km(points: list[tuple[float, float]]) -> float:
    return sum(haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:], strict=False))


def simplify_route(
    points: list[tuple[float, float]],
    tolerance_km: float,
    max_points: int,
) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return [_round_point(point) for point in points]
    simplified = _douglas_peucker(points, tolerance_km)
    if len(simplified) > max_points:
        simplified = resample_route(simplified, max_points)
    return [_round_point(point) for point in simplified]


def resample_route(points: list[tuple[float, float]], sample_count: int) -> list[tuple[float, float]]:
    if len(points) <= sample_count:
        return points[:]
    distances = [0.0]
    for prev, current in zip(points, points[1:], strict=False):
        distances.append(distances[-1] + haversine_km(prev[0], prev[1], current[0], current[1]))
    total = distances[-1]
    if total == 0:
        return [points[0]] * sample_count
    sampled: list[tuple[float, float]] = []
    cursor = 0
    for index in range(sample_count):
        target = total * index / (sample_count - 1)
        while cursor < len(distances) - 2 and distances[cursor + 1] < target:
            cursor += 1
        span = distances[cursor + 1] - distances[cursor]
        ratio = 0 if span == 0 else (target - distances[cursor]) / span
        lat = points[cursor][0] + (points[cursor + 1][0] - points[cursor][0]) * ratio
        lon = points[cursor][1] + (points[cursor + 1][1] - points[cursor][1]) * ratio
        sampled.append((lat, lon))
    return sampled


def _iter_trace_payloads_from_dir(path: Path) -> Iterable[tuple[str, bytes]]:
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        if not _looks_like_trace_file(item):
            continue
        payload = _read_trace_file(item)
        if payload is not None:
            yield str(item), payload


def _iter_trace_payloads_from_tar(path: Path) -> Iterable[tuple[str, bytes]]:
    with path.open("rb") as handle:
        yield from _iter_trace_payloads_from_tarfile(handle, label=path.name)


def _iter_trace_payloads_from_tarfile(handle: BinaryIO, label: str) -> Iterable[tuple[str, bytes]]:
    traces = 0
    with tarfile.open(fileobj=handle, mode="r|*") as archive:
        for member in archive:
            if not member.isfile() or not _looks_like_trace_name(member.name):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            raw = _try_decompress_gzip(extracted.read(), f"{label}:{member.name}")
            if raw is None:
                continue
            traces += 1
            if traces % 10000 == 0:
                print(f"read {traces:,} traces from {label}", file=sys.stderr, flush=True)
            yield f"{label}:{member.name}", raw


def _read_trace_file(path: Path) -> bytes | None:
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rb") as handle:
                return handle.read()
        return _try_decompress_gzip(path.read_bytes(), str(path))
    except OSError:
        return None


def _douglas_peucker(points: list[tuple[float, float]], tolerance_km: float) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points
    start = points[0]
    end = points[-1]
    max_distance = -1.0
    split_index = 0
    for index, point in enumerate(points[1:-1], start=1):
        distance = _point_line_distance_km(point, start, end)
        if distance > max_distance:
            max_distance = distance
            split_index = index
    if max_distance <= tolerance_km:
        return [start, end]
    left = _douglas_peucker(points[: split_index + 1], tolerance_km)
    right = _douglas_peucker(points[split_index:], tolerance_km)
    return left[:-1] + right


def _point_line_distance_km(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    mean_lat = math.radians((start[0] + end[0] + point[0]) / 3)
    scale_x = 111.320 * math.cos(mean_lat)
    scale_y = 110.574
    px, py = point[1] * scale_x, point[0] * scale_y
    sx, sy = start[1] * scale_x, start[0] * scale_y
    ex, ey = end[1] * scale_x, end[0] * scale_y
    dx, dy = ex - sx, ey - sy
    if dx == 0 and dy == 0:
        return math.hypot(px - sx, py - sy)
    ratio = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / (dx * dx + dy * dy)))
    closest_x = sx + ratio * dx
    closest_y = sy + ratio * dy
    return math.hypot(px - closest_x, py - closest_y)


def _variant_payload(variant: ObservedVariant, include_sources: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "signature": variant.signature,
        "sampleCount": variant.sample_count,
        "distanceKm": round(variant.representative_distance_km, 1),
        "points": [[lat, lon] for lat, lon in variant.representative_points],
        "exampleFlights": sorted(variant.example_flights)[:8],
    }
    if variant.start_dates:
        payload["dateRange"] = [min(variant.start_dates), max(variant.start_dates)]
    if include_sources:
        payload["sourceFiles"] = sorted(variant.source_files)[:8]
    return payload


def _trace_timestamp(trace: dict[str, Any], leg: list[TracePoint]) -> float | None:
    timestamp = _maybe_float(trace.get("timestamp"))
    if timestamp is None:
        return None
    return timestamp + (leg[0].elapsed_s if leg else 0)


def _most_common_callsign(points: list[TracePoint]) -> str | None:
    counts = Counter(point.callsign for point in points if point.callsign)
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _clean_callsign(value: Any) -> str | None:
    if not value:
        return None
    clean = str(value).strip().upper()
    return clean or None


def _altitude_ft(value: Any) -> float | None:
    if value == "ground":
        return 0.0
    return _maybe_float(value)


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_point(point: tuple[float, float]) -> tuple[float, float]:
    return (round(point[0], 5), round(point[1], 5))


def _looks_like_tar(path: Path) -> bool:
    name = path.name
    return name.endswith(".tar") or ".tar." in name or name.endswith(".tar.gz") or name.endswith(".tgz")


def _looks_like_tar_part(path: Path) -> bool:
    return _looks_like_tar(path) or bool(re.search(r"\.tar\.[a-z]{2,}$", path.name))


def _looks_like_trace_file(path: Path) -> bool:
    return _looks_like_trace_name(str(path))


def _looks_like_trace_name(name: str) -> bool:
    lowered = name.lower()
    return "trace" in lowered and (lowered.endswith(".json") or lowered.endswith(".json.gz"))


def _normalize_release_date(value: str) -> str | None:
    match = re.search(r"(\d{4})[.-](\d{2})[.-](\d{2})", value)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def _maybe_decompress_gzip(raw: bytes) -> bytes:
    if raw.startswith(b"\x1f\x8b"):
        return gzip.decompress(raw)
    return raw


def _try_decompress_gzip(raw: bytes, label: str) -> bytes | None:
    try:
        return _maybe_decompress_gzip(raw)
    except (EOFError, OSError, zlib.error) as exc:
        print(f"skip corrupt trace payload {label}: {exc}", file=sys.stderr, flush=True)
        return None
