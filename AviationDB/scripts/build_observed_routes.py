#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))

from aviationdb.observed_routes import (  # noqa: E402
    AirportIndex,
    BuildOptions,
    build_observed_routes,
    build_observed_routes_from_payloads,
    download_release,
    fetch_preferred_releases,
    groups_to_payload,
    iter_trace_payloads_from_split_tar,
    iter_trace_payloads_from_split_urls,
    release_parts_from_dir,
    write_payload,
)

DEFAULT_AIRPORT_INDEX = ROOT / "shared" / "offline-packs" / "core-global" / "airports-index.json"
DEFAULT_RAW_DIR = PROJECT / "data" / "raw" / "adsblol"
DEFAULT_OUTPUT = (
    PROJECT / "data" / "releases" / "private" / "observed-routes" / "adsblol" / "observed-routes.global.json.gz"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build compact representative offline flight routes from ADSB.lol globe_history traces."
    )
    parser.add_argument("--airport-index", type=Path, default=DEFAULT_AIRPORT_INDEX)
    parser.add_argument(
        "--input",
        action="append",
        type=Path,
        default=[],
        help="Extracted traces dir, trace file, or tar file.",
    )
    parser.add_argument(
        "--release-dir",
        action="append",
        type=Path,
        default=[],
        help="Directory containing one ADSB.lol split-tar daily release.",
    )
    parser.add_argument("--year", type=int, help="Fetch ADSB.lol PREFERRED_RELEASES for this year.")
    parser.add_argument(
        "--date",
        action="append",
        default=[],
        help="Release date to download/process, e.g. 2025-07-21.",
    )
    parser.add_argument("--start-date", help="First release date for a contiguous run, e.g. 2025-07-01.")
    parser.add_argument("--days", type=int, help="Number of dates to process from --start-date.")
    parser.add_argument("--download", action="store_true", help="Download the requested release date part files first.")
    parser.add_argument(
        "--stream-download",
        action="store_true",
        help="Read GitHub release assets directly without storing raw tar parts.",
    )
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-points", type=int, default=8)
    parser.add_argument("--min-route-km", type=float, default=120)
    parser.add_argument("--max-airport-km", type=float, default=150)
    parser.add_argument("--max-trace-gap-s", type=float, default=2700)
    parser.add_argument("--simplify-tolerance-km", type=float, default=8)
    parser.add_argument("--max-points-per-route", type=int, default=96)
    parser.add_argument("--signature-samples", type=int, default=14)
    parser.add_argument("--signature-quantum-deg", type=float, default=0.5)
    parser.add_argument("--max-track-detour-ratio", type=float, default=2.6)
    parser.add_argument("--limit-traces", type=int)
    parser.add_argument("--pretty-summary", action="store_true")
    args = parser.parse_args()

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
        limit_traces=args.limit_traces,
    )

    if args.download and args.stream_download:
        parser.error("Use either --download or --stream-download, not both.")

    dates = [_normalize_cli_date(item) for item in args.date]
    if args.start_date or args.days:
        if not args.start_date or not args.days:
            parser.error("--start-date and --days must be used together.")
        dates.extend(_date_range(args.start_date, args.days))

    inputs = list(args.input)
    source_urls: list[str] = []
    split_urls = []
    if dates:
        if args.year is None:
            parser.error("--year is required when release dates are used.")
        releases = fetch_preferred_releases(args.year)
        for release_date in dates:
            entry = releases.get(release_date)
            if entry is None:
                parser.error(f"No ADSB.lol preferred release found for {release_date}.")
            source_urls.extend(entry.urls)
            if args.stream_download:
                print(f"streaming {entry.date}: {len(entry.urls)} release asset(s)", file=sys.stderr, flush=True)
                split_urls.append(entry.urls)
            elif args.download:
                print(f"downloading {entry.date}: {len(entry.urls)} release asset(s)", file=sys.stderr, flush=True)
                downloaded = download_release(entry, args.raw_dir)
                inputs.extend(downloaded if len(downloaded) == 1 else [])
                if len(downloaded) > 1:
                    args.release_dir.append(args.raw_dir / entry.date)
            else:
                args.release_dir.append(args.raw_dir / entry.date)

    split_payloads = []
    for release_dir in args.release_dir:
        parts = release_parts_from_dir(release_dir)
        if not parts:
            parser.error(f"No tar release parts found in {release_dir}.")
        if len(parts) == 1:
            inputs.append(parts[0])
        else:
            split_payloads.append(parts)

    if not inputs and not split_payloads and not split_urls:
        parser.error("Provide --input, --release-dir, or --year/--date.")

    airport_index = AirportIndex.from_json(args.airport_index)
    groups, stats = build_observed_routes(inputs, airport_index, options)
    for urls in split_urls:
        print(f"processing streamed release: {len(urls)} asset(s)", file=sys.stderr, flush=True)
        extra_groups, extra_stats = build_observed_routes_from_payloads(
            iter_trace_payloads_from_split_urls(urls),
            airport_index,
            options,
        )
        _merge_groups(groups, extra_groups)
        stats = _merge_stats(stats, extra_stats)
        print(
            "release done: "
            f"routes={len(groups)} traces={stats.traces_parsed} accepted={stats.samples_accepted}",
            file=sys.stderr,
            flush=True,
        )
    for parts in split_payloads:
        extra_groups, extra_stats = build_observed_routes_from_payloads(
            iter_trace_payloads_from_split_tar(parts),
            airport_index,
            options,
        )
        _merge_groups(groups, extra_groups)
        stats = _merge_stats(stats, extra_stats)

    payload = groups_to_payload(groups, stats, source_urls, options)
    write_payload(payload, args.output)
    summary = {
        "output": str(args.output),
        "routes": len(payload["routes"]),
        "stats": payload["stats"],
        "bytes": args.output.stat().st_size,
    }
    print(json.dumps(summary, indent=2 if args.pretty_summary else None, ensure_ascii=False))
    return 0


def _merge_groups(target: dict, source: dict) -> None:
    for key, group in source.items():
        if key not in target:
            target[key] = group
            continue
        for signature, variant in group.variants.items():
            existing = target[key].variants.setdefault(signature, variant)
            if existing is variant:
                continue
            existing.sample_count += variant.sample_count
            existing.distance_sum_km += variant.distance_sum_km
            if variant.sample_count > 0 and (
                not existing.representative_points
                or variant.representative_distance_km < existing.representative_distance_km
            ):
                existing.representative_points = variant.representative_points
                existing.representative_distance_km = variant.representative_distance_km
            existing.example_flights.update(variant.example_flights)
            existing.source_files.update(variant.source_files)
            existing.start_dates.extend(variant.start_dates)


def _merge_stats(left, right):
    return type(left)(
        traces_seen=left.traces_seen + right.traces_seen,
        traces_parsed=left.traces_parsed + right.traces_parsed,
        legs_seen=left.legs_seen + right.legs_seen,
        samples_accepted=left.samples_accepted + right.samples_accepted,
        samples_rejected=left.samples_rejected + right.samples_rejected,
    )


def _normalize_cli_date(value: str) -> str:
    return value.replace(".", "-")


def _date_range(start: str, days: int) -> list[str]:
    if days <= 0:
        raise argparse.ArgumentTypeError("--days must be positive.")
    current = datetime.strptime(_normalize_cli_date(start), "%Y-%m-%d").date()
    return [(current + timedelta(days=offset)).isoformat() for offset in range(days)]


if __name__ == "__main__":
    raise SystemExit(main())
