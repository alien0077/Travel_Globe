from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from aviationdb.build import build_all, build_source
from aviationdb.config import PROJECT_ROOT, source_config
from aviationdb.download import download_source
from aviationdb.exporters.app_pack import export_app_pack
from aviationdb.logging import configure_logging
from aviationdb.repository import AviationRepository
from aviationdb.routing import route_between_airports
from aviationdb.validation import validate_database, write_reports

DEFAULT_DB = PROJECT_ROOT / "data" / "processed" / "aviation.sqlite"
DEFAULT_REPORTS = PROJECT_ROOT / "data" / "reports"
ROOT = PROJECT_ROOT.parent
SHARED_AVIATION_DIR = ROOT / "shared" / "offline-packs" / "aviation"
PUBLIC_AVIATION_DIR = ROOT / "replay-engine" / "public" / "offline-packs" / "aviation"
PRIVATE_AVIATION_DIR = PROJECT_ROOT / "data" / "releases" / "private" / "aviation"


def main() -> None:
    configure_logging()
    parser = _parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aviationdb")
    parser.add_argument("--database", default=str(DEFAULT_DB))
    subparsers = parser.add_subparsers(dest="command")

    source = subparsers.add_parser("source")
    source_sub = source.add_subparsers(dest="source_command")
    source_list = source_sub.add_parser("list")
    source_list.set_defaults(func=_source_list)
    source_inspect = source_sub.add_parser("inspect")
    source_inspect.add_argument("source_id")
    source_inspect.set_defaults(func=_source_inspect)

    build = subparsers.add_parser("build")
    build.add_argument("source_id")
    build.set_defaults(func=_build)

    download = subparsers.add_parser("download")
    download.add_argument("source_id")
    download.set_defaults(func=_download)

    build_all_cmd = subparsers.add_parser("build-all")
    build_all_cmd.set_defaults(func=_build_all)

    validate = subparsers.add_parser("validate")
    validate.add_argument("target", nargs="?", default="all")
    validate.set_defaults(func=_validate)

    export = subparsers.add_parser("export")
    export_sub = export.add_subparsers(dest="export_command")
    app_pack = export_sub.add_parser("app-pack")
    app_pack.add_argument("--region", default="asia-east")
    app_pack.add_argument("--output-dir")
    app_pack.add_argument("--private", action="store_true", dest="include_private")
    app_pack.set_defaults(func=_export_app_pack)

    route = subparsers.add_parser("route")
    route.add_argument("origin")
    route.add_argument("destination")
    route.add_argument("--region", default="asia-east")
    route.set_defaults(func=_route)
    return parser


def _repo(args: argparse.Namespace) -> AviationRepository:
    repo = AviationRepository(Path(args.database))
    repo.init_schema()
    return repo


def _source_list(_args: argparse.Namespace) -> None:
    for source_id, item in source_config()["sources"].items():
        print(f"{source_id}\t{item['provider']}\t{item['redistribution_status']}")


def _source_inspect(args: argparse.Namespace) -> None:
    print(json.dumps(source_config()["sources"][args.source_id], indent=2, ensure_ascii=False))


def _build(args: argparse.Namespace) -> None:
    repo = _repo(args)
    dataset = build_source(repo, args.source_id)
    print(
        json.dumps(
            {
                "source": args.source_id,
                "airports": len(dataset.airports),
                "points": len(dataset.points),
                "airways": len(dataset.airways),
                "segments": len(dataset.segments),
                "issues": len(dataset.issues),
            },
            indent=2,
        )
    )
    repo.close()


def _download(args: argparse.Namespace) -> None:
    config = source_config()["sources"][args.source_id]
    result = download_source(args.source_id, config)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _build_all(args: argparse.Namespace) -> None:
    repo = _repo(args)
    results = build_all(repo)
    issues = validate_database(repo)
    write_reports(repo, DEFAULT_REPORTS)
    manifest = export_app_pack(repo, "asia-east", SHARED_AVIATION_DIR)
    _mirror_public_pack()
    print(
        json.dumps(
            {
                "sources": {key: _dataset_summary(value) for key, value in results.items()},
                "validationIssues": len(issues),
                "manifest": manifest["id"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    repo.close()


def _validate(args: argparse.Namespace) -> None:
    repo = _repo(args)
    issues = validate_database(repo)
    write_reports(repo, DEFAULT_REPORTS)
    print(json.dumps({"target": args.target, "issues": [issue.__dict__ for issue in issues]}, indent=2))
    repo.close()


def _export_app_pack(args: argparse.Namespace) -> None:
    repo = _repo(args)
    output_dir = Path(args.output_dir) if args.output_dir else _default_export_dir(args.region, args.include_private)
    manifest = export_app_pack(repo, args.region, output_dir, include_private=args.include_private)
    if not args.include_private:
        _mirror_public_pack()
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    repo.close()


def _route(args: argparse.Namespace) -> None:
    repo = _repo(args)
    result = route_between_airports(repo, args.origin, args.destination, args.region)
    print(json.dumps(result.__dict__, indent=2, ensure_ascii=False))
    repo.close()


def _dataset_summary(dataset: Any) -> dict[str, int]:
    return {
        "airports": len(dataset.airports),
        "points": len(dataset.points),
        "airways": len(dataset.airways),
        "segments": len(dataset.segments),
        "issues": len(dataset.issues),
    }


def _default_export_dir(region: str, include_private: bool) -> Path:
    if include_private:
        return PRIVATE_AVIATION_DIR / region
    return SHARED_AVIATION_DIR


def _mirror_public_pack() -> None:
    if PUBLIC_AVIATION_DIR.exists():
        shutil.rmtree(PUBLIC_AVIATION_DIR)
    shutil.copytree(SHARED_AVIATION_DIR, PUBLIC_AVIATION_DIR)


if __name__ == "__main__":
    main()
