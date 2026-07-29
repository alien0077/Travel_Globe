#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import re
import subprocess
import sys
import time
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))

from aviationdb.observed_routes import (  # noqa: E402
    Airport,
    AirportIndex,
    BuildOptions,
    BuildStats,
    ObservedRouteGroup,
    ObservedVariant,
    build_observed_routes_from_payloads,
    fetch_preferred_releases,
    groups_to_payload,
    iter_trace_payloads_from_split_tar,
    write_payload,
)

DEFAULT_AIRPORT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "airports-index.json"
DEFAULT_WORK_DIR = Path("/private/tmp/travel-globe-adsblol")
DEFAULT_OUTPUT = (
    PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "observed-routes.global.json.gz"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Robust range builder for ADSB.lol observed route packs using curl resume per daily release."
    )
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed-pack", type=Path, help="Existing observed route pack to merge before processing dates.")
    parser.add_argument("--cleanup-downloads", action="store_true")
    parser.add_argument("--min-points", type=int, default=8)
    parser.add_argument("--min-route-km", type=float, default=120)
    parser.add_argument("--max-airport-km", type=float, default=150)
    parser.add_argument("--max-trace-gap-s", type=float, default=2700)
    parser.add_argument("--simplify-tolerance-km", type=float, default=8)
    parser.add_argument("--max-points-per-route", type=int, default=96)
    parser.add_argument("--signature-samples", type=int, default=14)
    parser.add_argument("--signature-quantum-deg", type=float, default=0.5)
    parser.add_argument("--max-track-detour-ratio", type=float, default=2.6)
    args = parser.parse_args()

    if args.days <= 0:
        parser.error("--days must be positive.")

    options = BuildOptions(
        min_points=args.min_points,
        min_route_km=args.min_route_km,
        max_airport_km=args.max_airport_km,
        max_trace_gap_s=args.max_trace_gap_s,
        simplify_tolerance_km=args.simplify_tolerance_km,
        max_points_per_route=args.max_points_per_route,
        signature_samples=args.signature_samples,
        signature_quantum_deg=args.signature_quantum_deg,
        max_track_detour_ratio=args.max_track_detour_ratio,
    )
    airport_index = AirportIndex.from_json(args.airport_index)
    releases = fetch_preferred_releases(args.year)
    dates = _date_range(args.start_date, args.days)
    groups: dict[str, ObservedRouteGroup] = {}
    stats = BuildStats(0, 0, 0, 0, 0)
    source_urls: list[str] = []
    if args.seed_pack:
        groups, stats, source_urls = _load_seed_pack(args.seed_pack)
        print(
            f"seed loaded: routes={len(groups)} traces={stats.traces_parsed} "
            f"accepted={stats.samples_accepted} urls={len(source_urls)}",
            file=sys.stderr,
            flush=True,
        )

    for index, release_date in enumerate(dates, start=1):
        entry = releases.get(release_date)
        if entry is None:
            raise SystemExit(f"No ADSB.lol preferred release found for {release_date}.")
        if entry.urls and all(url in source_urls for url in entry.urls):
            print(
                f"[{index}/{len(dates)}] skipping {entry.date}: already present in seed pack",
                file=sys.stderr,
                flush=True,
            )
            continue
        print(
            f"[{index}/{len(dates)}] downloading {entry.date}: {len(entry.urls)} asset(s)",
            file=sys.stderr,
            flush=True,
        )
        release_dir = args.work_dir / entry.date
        release_dir.mkdir(parents=True, exist_ok=True)
        parts = [_download_with_curl(url, release_dir) for url in entry.urls]
        print(f"[{index}/{len(dates)}] processing {entry.date}", file=sys.stderr, flush=True)
        day_groups, day_stats = build_observed_routes_from_payloads(
            iter_trace_payloads_from_split_tar(parts),
            airport_index,
            options,
        )
        _merge_groups(groups, day_groups)
        stats = _merge_stats(stats, day_stats)
        source_urls.extend(url for url in entry.urls if url not in source_urls)
        payload = groups_to_payload(groups, stats, source_urls, options)
        write_payload(payload, args.output)
        print(
            f"[{index}/{len(dates)}] checkpoint: routes={len(groups)} "
            f"traces={stats.traces_parsed} accepted={stats.samples_accepted} output={args.output.stat().st_size} bytes",
            file=sys.stderr,
            flush=True,
        )
        if args.cleanup_downloads:
            for part in parts:
                part.unlink(missing_ok=True)
            print(f"[{index}/{len(dates)}] cleaned downloaded parts for {entry.date}", file=sys.stderr, flush=True)

    summary = {
        "output": str(args.output),
        "routes": len(groups),
        "stats": stats.__dict__,
        "bytes": args.output.stat().st_size,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _download_with_curl(url: str, release_dir: Path) -> Path:
    target = release_dir / url.rstrip("/").split("/")[-1]
    chunk = release_dir / f".{target.name}.chunk"
    headers = release_dir / f".{target.name}.headers"
    print(f"downloading asset: {target.name}", file=sys.stderr, flush=True)
    if chunk.exists():
        with suppress(RuntimeError):
            _append_download_chunk(target, chunk, headers, target.stat().st_size if target.exists() else 0)
    expected_size = _expected_download_size(headers)
    if expected_size is not None and target.exists() and target.stat().st_size == expected_size:
        print(f"using cached complete asset: {target.name} ({expected_size} bytes)", file=sys.stderr, flush=True)
        return target
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(1, 61):
        offset = target.stat().st_size if target.exists() else 0
        chunk.unlink(missing_ok=True)
        headers.unlink(missing_ok=True)
        command = [
            "curl",
            "-fL",
            "-sS",
            "--http1.1",
            "--retry",
            "0",
            "--connect-timeout",
            "30",
            "--speed-time",
            "90",
            "--speed-limit",
            "1024",
            "-D",
            str(headers),
            "-o",
            str(chunk),
        ]
        if offset > 0:
            command.extend(["-r", f"{offset}-"])
        command.append(url)
        try:
            subprocess.run(command, check=True)
            _append_download_chunk(target, chunk, headers, offset)
            break
        except subprocess.CalledProcessError as error:
            last_error = error
            if _headers_status_code(headers) == 416 and target.exists() and target.stat().st_size > 0:
                print(
                    f"using cached complete asset after HTTP 416: {target.name} ({target.stat().st_size} bytes)",
                    file=sys.stderr,
                    flush=True,
                )
                return target
            appended = _append_download_chunk(target, chunk, headers, offset)
            size = target.stat().st_size if target.exists() else 0
            print(
                f"download retry {attempt}/60 failed for {target.name}; "
                f"appended={appended} bytes partial={size} bytes",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(min(60, attempt * 5))
    else:
        raise last_error or RuntimeError(f"Unable to download {url}")
    print(f"downloaded asset: {target.name} ({target.stat().st_size} bytes)", file=sys.stderr, flush=True)
    return target


def _append_download_chunk(target: Path, chunk: Path, headers: Path, offset: int) -> int:
    if not chunk.exists() or chunk.stat().st_size == 0:
        return 0
    if offset > 0 and not _headers_include_content_range(headers):
        raise RuntimeError(f"Refusing to append non-range response to partial download: {target.name}")
    appended = chunk.stat().st_size
    with target.open("ab") as output, chunk.open("rb") as input_file:
        while True:
            block = input_file.read(1024 * 1024)
            if not block:
                break
            output.write(block)
    chunk.unlink(missing_ok=True)
    return appended


def _headers_include_content_range(path: Path) -> bool:
    if not path.exists():
        return False
    return "content-range:" in path.read_text(encoding="utf-8", errors="replace").lower()


def _headers_status_code(path: Path) -> int | None:
    if not path.exists():
        return None
    matches = re.findall(r"^HTTP/\S+\s+(\d+)", path.read_text(encoding="utf-8", errors="replace"), flags=re.MULTILINE)
    if not matches:
        return None
    return int(matches[-1])


def _expected_download_size(path: Path) -> int | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    range_matches = re.findall(r"content-range:\s*bytes\s+\d+-\d+/(\d+)", text, flags=re.IGNORECASE)
    if range_matches:
        return int(range_matches[-1])
    length_matches = re.findall(r"content-length:\s*(\d+)", text, flags=re.IGNORECASE)
    for value in reversed(length_matches):
        size = int(value)
        if size > 0:
            return size
    return None


def _merge_groups(target: dict, source: dict) -> None:
    for key, group in source.items():
        if key not in target:
            target[key] = group
            continue
        for signature, variant in group.variants.items():
            existing = target[key].variants.setdefault(signature, variant)
            if existing is variant:
                continue
            should_replace_representative = variant.sample_count > existing.sample_count
            existing.sample_count += variant.sample_count
            existing.distance_sum_km += variant.distance_sum_km
            if should_replace_representative:
                existing.representative_points = variant.representative_points
                existing.representative_distance_km = variant.representative_distance_km
            existing.example_flights.update(variant.example_flights)
            existing.source_files.update(variant.source_files)
            existing.start_dates.extend(variant.start_dates)


def _merge_stats(left: BuildStats, right: BuildStats) -> BuildStats:
    return BuildStats(
        traces_seen=left.traces_seen + right.traces_seen,
        traces_parsed=left.traces_parsed + right.traces_parsed,
        legs_seen=left.legs_seen + right.legs_seen,
        samples_accepted=left.samples_accepted + right.samples_accepted,
        samples_rejected=left.samples_rejected + right.samples_rejected,
    )


def _load_seed_pack(path: Path) -> tuple[dict[str, ObservedRouteGroup], BuildStats, list[str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    groups: dict[str, ObservedRouteGroup] = {}
    for route in payload.get("routes", []):
        origin = Airport(
            iata=route["originIata"],
            icao=route.get("originIcao", ""),
            name=route.get("originName", route["originIata"]),
            airport_type="",
            lat=0.0,
            lon=0.0,
        )
        destination = Airport(
            iata=route["destinationIata"],
            icao=route.get("destinationIcao", ""),
            name=route.get("destinationName", route["destinationIata"]),
            airport_type="",
            lat=0.0,
            lon=0.0,
        )
        group = ObservedRouteGroup(
            route_key=f"{origin.iata}-{destination.iata}",
            origin=origin,
            destination=destination,
        )
        for item in route.get("variants", []):
            variant = ObservedVariant(signature=item["signature"])
            variant.sample_count = int(item.get("sampleCount", 0))
            variant.distance_sum_km = float(item.get("distanceKm", 0)) * variant.sample_count
            variant.representative_distance_km = float(item.get("distanceKm", 0))
            variant.representative_points = [(float(lat), float(lon)) for lat, lon in item.get("points", [])]
            variant.example_flights.update(item.get("exampleFlights", []))
            variant.source_files.update(item.get("sourceFiles", []))
            date_range = item.get("dateRange") or []
            variant.start_dates.extend(str(value) for value in date_range)
            group.variants[variant.signature] = variant
        if not group.variants and route.get("representative"):
            item = route["representative"]
            variant = ObservedVariant(signature=item.get("signature", "seed"))
            variant.sample_count = int(item.get("sampleCount", route.get("sampleCount", 0)))
            variant.distance_sum_km = float(item.get("distanceKm", 0)) * variant.sample_count
            variant.representative_distance_km = float(item.get("distanceKm", 0))
            variant.representative_points = [(float(lat), float(lon)) for lat, lon in item.get("points", [])]
            variant.example_flights.update(item.get("exampleFlights", []))
            group.variants[variant.signature] = variant
        groups[group.route_key] = group
    raw_stats = payload.get("stats") or {}
    stats = BuildStats(
        traces_seen=int(raw_stats.get("traces_seen", 0)),
        traces_parsed=int(raw_stats.get("traces_parsed", 0)),
        legs_seen=int(raw_stats.get("legs_seen", 0)),
        samples_accepted=int(raw_stats.get("samples_accepted", 0)),
        samples_rejected=int(raw_stats.get("samples_rejected", 0)),
    )
    source_urls = list(payload.get("source", {}).get("releaseUrls", []))
    return groups, stats, source_urls


def _date_range(start: str, days: int) -> list[str]:
    current = datetime.strptime(start.replace(".", "-"), "%Y-%m-%d").date()
    return [(current + timedelta(days=offset)).isoformat() for offset in range(days)]


if __name__ == "__main__":
    raise SystemExit(main())
