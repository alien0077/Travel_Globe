from __future__ import annotations

import gzip
import io
import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from aviationdb.models import REDISTRIBUTION_ALLOWED
from aviationdb.repository import AviationRepository
from aviationdb.validation import coverage_report

REGION_COUNTRIES = {
    "asia-east": {"TW", "JP", "KR", "HK"},
    "north-america": {"US", "CA"},
    "central-america": {"BZ", "CR", "CS", "GT", "HN", "NI", "PA", "SV"},
    "asia-southeast": {"BN", "ID", "KH", "LA", "MM", "MY", "PH", "SG", "TH", "VN"},
    "south-asia": {"BD", "IN", "LK", "MV", "NP", "PK"},
    "south-america": {"AR", "BR", "CL", "CO", "EC", "PE", "UY", "VE"},
    "africa": {"ASECNA", "BW", "EG", "ET", "GH", "KE", "MA", "MU", "NG", "SC", "ZA"},
    "middle-east": {"AE", "BH", "IL", "JO", "KW", "OM", "QA", "SA", "TR"},
    "europe": {
        "AT",
        "BE",
        "CH",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GB",
        "GR",
        "HU",
        "IE",
        "IS",
        "IT",
        "LU",
        "LV",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "SE",
    },
}


def export_app_pack(
    repository: AviationRepository,
    region: str,
    output_dir: Path,
    *,
    include_private: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    region_dir = output_dir / "regions"
    region_dir.mkdir(parents=True, exist_ok=True)

    payload = _region_payload(repository, region, include_private=include_private)
    payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    json_path = region_dir / f"{region}.airgraph.json"
    gzip_path = region_dir / f"{region}.airgraph.json.gz"
    json_path.write_bytes(payload_bytes + b"\n")
    gzip_path.write_bytes(_gzip_bytes(payload_bytes))

    payload_sha = sha256(gzip_path.read_bytes()).hexdigest()
    coverage = coverage_report(repository)
    validation = {
        "issues": [
            dict(row)
            for row in repository.rows(
                """
                SELECT severity, code, message, source_id, entity_uid
                FROM validation_issue ORDER BY severity, code
                """
            )
        ]
    }
    coverage_path = output_dir / "coverage_report.json"
    validation_path = output_dir / "validation_report.json"
    coverage_path.write_text(json.dumps(coverage, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    validation_path.write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    payload_path = (
        f"regions/{region}.airgraph.json.gz"
        if include_private
        else f"shared/offline-packs/aviation/regions/{region}.airgraph.json.gz"
    )
    coverage_report_path = (
        "coverage_report.json" if include_private else "shared/offline-packs/aviation/coverage_report.json"
    )
    validation_report_path = (
        "validation_report.json" if include_private else "shared/offline-packs/aviation/validation_report.json"
    )

    manifest = {
        "id": "aviation-airgraph",
        "version": "0.1.0",
        "generatedAt": _generated_at(),
        "licenseMode": "private" if include_private else "public",
        "regions": [
            {
                "id": region,
                "countries": sorted(REGION_COUNTRIES.get(region, [])),
                "airports": len(payload["airports"]),
                "points": len(payload["points"]),
                "segments": len(payload["segments"]),
                "airways": len(payload["airways"]),
            }
        ],
        "sources": payload["sources"],
        "payloads": {
            "airgraph": [
                {
                    "path": payload_path,
                    "bytes": gzip_path.stat().st_size,
                    "sha256": payload_sha,
                    "contentType": "application/json+gzip",
                    "public": not include_private,
                }
            ],
            "reports": [
                _json_entry(coverage_report_path, coverage_path, public=not include_private),
                _json_entry(validation_report_path, validation_path, public=not include_private),
            ],
        },
    }
    manifest_path = output_dir / "aviation-pack-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def _region_payload(repository: AviationRepository, region: str, *, include_private: bool = False) -> dict[str, Any]:
    countries = REGION_COUNTRIES.get(region, set())
    placeholders = ",".join("?" for _ in countries) or "''"
    source_filter = "" if include_private else "AND s.redistribution_status = ? AND s.allow_app_bundle = 1"
    filter_args: tuple[object, ...] = tuple(countries)
    if not include_private:
        filter_args = filter_args + (REDISTRIBUTION_ALLOWED,)
    points_rows = repository.rows(
        f"""
        SELECT p.*
        FROM nav_point p
        JOIN source_metadata s ON s.source_id = p.source_id
        WHERE p.country IN ({placeholders})
          {source_filter}
        ORDER BY p.ident, p.uid
        """,
        filter_args,
    )
    point_index = {row["uid"]: index for index, row in enumerate(points_rows)}
    points = [
        [row["ident"], round(row["latitude"], 6), round(row["longitude"], 6), row["point_type"], row["source_id"]]
        for row in points_rows
    ]

    airways_rows = repository.rows(
        f"""
        SELECT DISTINCT a.*
        FROM airway a
        JOIN source_metadata s ON s.source_id = a.source_id
        WHERE a.country IN ({placeholders})
          {source_filter}
        ORDER BY a.designator, a.uid
        """,
        filter_args,
    )
    airway_index = {row["uid"]: index for index, row in enumerate(airways_rows)}
    airways = [[row["designator"], row["route_type"], row["source_id"]] for row in airways_rows]

    segments = []
    for row in repository.rows(
        """
        SELECT airway_uid, from_point_uid, to_point_uid, distance_nm, direction
        FROM airway_segment
        ORDER BY airway_uid, sequence
        """
    ):
        if (
            row["airway_uid"] in airway_index
            and row["from_point_uid"] in point_index
            and row["to_point_uid"] in point_index
        ):
            segments.append(
                [
                    point_index[row["from_point_uid"]],
                    point_index[row["to_point_uid"]],
                    airway_index[row["airway_uid"]],
                    round(float(row["distance_nm"] or 0), 2),
                    row["direction"] or "",
                ]
            )

    airport_rows = repository.rows(
        f"""
        SELECT a.*
        FROM airport a
        JOIN source_metadata s ON s.source_id = a.source_id
        WHERE a.country IN ({placeholders})
          {source_filter}
        ORDER BY COALESCE(a.iata, a.icao)
        """,
        filter_args,
    )
    airports = [
        [row["icao"], row["iata"], row["name"], round(row["latitude"], 6), round(row["longitude"], 6), row["country"]]
        for row in airport_rows
    ]
    exported_source_ids = sorted(
        {
            row["source_id"]
            for rows in (points_rows, airways_rows)
            for row in rows
        }
        | {row["source_id"] for row in airport_rows}
    )
    source_placeholders = ",".join("?" for _ in exported_source_ids) or "''"
    source_metadata_filter = "" if include_private else "AND redistribution_status = ? AND allow_app_bundle = 1"
    source_metadata_args: tuple[object, ...] = tuple(exported_source_ids)
    if not include_private:
        source_metadata_args = source_metadata_args + (REDISTRIBUTION_ALLOWED,)
    sources = [
        {
            "sourceId": row["source_id"],
            "provider": row["provider"],
            "country": row["country"],
            "redistributionStatus": row["redistribution_status"],
            "airacCycle": row["airac_cycle"],
        }
        for row in repository.rows(
            f"""
            SELECT source_id, provider, country, redistribution_status, airac_cycle
            FROM source_metadata
            WHERE source_id IN ({source_placeholders})
              {source_metadata_filter}
            ORDER BY source_id
            """,
            source_metadata_args,
        )
    ]
    return {
        "schemaVersion": 1,
        "region": region,
        "generatedAt": _generated_at(),
        "sources": sources,
        "airports": airports,
        "points": points,
        "airways": airways,
        "segments": segments,
    }


def _generated_at() -> str:
    return os.environ.get("AVIATIONDB_GENERATED_AT") or datetime.now(UTC).isoformat()


def _gzip_bytes(payload: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as handle:
        handle.write(payload)
    return output.getvalue()


def _json_entry(path: str, local_path: Path, *, public: bool) -> dict[str, Any]:
    data = local_path.read_bytes()
    return {
        "path": path,
        "bytes": len(data),
        "sha256": sha256(data).hexdigest(),
        "contentType": "application/json",
        "public": public,
    }
