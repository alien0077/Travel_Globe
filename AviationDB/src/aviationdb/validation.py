from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from aviationdb.geo import haversine_nm
from aviationdb.models import Issue
from aviationdb.repository import AviationRepository


def validate_database(repository: AviationRepository) -> list[Issue]:
    repository.clear_validation_issues()
    issues: list[Issue] = []
    issues.extend(_validate_points(repository))
    issues.extend(_validate_airways(repository))
    issues.extend(_validate_segments(repository))
    for issue in issues:
        repository.add_validation_issue(issue)
    return issues


def coverage_report(repository: AviationRepository) -> dict[str, object]:
    countries = {}
    for row in repository.rows(
        """
        SELECT COALESCE(country, 'UNKNOWN') AS country, COUNT(*) AS points
        FROM nav_point GROUP BY COALESCE(country, 'UNKNOWN')
        """
    ):
        country = row["country"]
        country_value = None if country == "UNKNOWN" else country
        countries[country] = {
            "waypoints": row["points"],
            "airports": repository.scalar(
                "SELECT COUNT(*) FROM airport WHERE country IS ?",
                (country_value,),
            )
            or 0,
            "airways": repository.scalar(
                "SELECT COUNT(*) FROM airway WHERE country IS ?",
                (country_value,),
            )
            or 0,
            "segments": repository.scalar(
                """
                SELECT COUNT(*)
                FROM airway_segment s
                JOIN airway a ON a.uid = s.airway_uid
                WHERE a.country IS ?
                """,
                (country_value,),
            )
            or 0,
        }

    known_points = {}
    for ident in ["ELATO", "MAKOT", "KAPLI", "TONGA"]:
        matches = [
            {
                "uid": row["uid"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "source_id": row["source_id"],
            }
            for row in repository.rows(
                "SELECT uid, latitude, longitude, source_id FROM nav_point WHERE ident = ?",
                (ident,),
            )
        ]
        known_points[ident] = {"found": bool(matches), "matches": matches}

    validation_counts = Counter(
        row["severity"] for row in repository.rows("SELECT severity FROM validation_issue")
    )
    return {
        "generated_at": repository.scalar("SELECT datetime('now')"),
        "countries": countries,
        "known_points": known_points,
        "validation": {
            "errors": validation_counts["error"],
            "warnings": validation_counts["warning"],
        },
    }


def write_reports(repository: AviationRepository, reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    coverage = coverage_report(repository)
    issues = [
        dict(row)
        for row in repository.rows(
            "SELECT severity, code, message, source_id, entity_uid FROM validation_issue ORDER BY severity, code"
        )
    ]
    (reports_dir / "coverage_report.json").write_text(
        json.dumps(coverage, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (reports_dir / "validation_report.json").write_text(
        json.dumps({"issues": issues}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _validate_points(repository: AviationRepository) -> list[Issue]:
    issues: list[Issue] = []
    for row in repository.rows("SELECT uid, ident, latitude, longitude, source_id FROM nav_point"):
        if not row["ident"].strip():
            issues.append(
                Issue("error", "point-empty-ident", "Point ident is empty", row["source_id"], row["uid"])
            )
        if not -90 <= row["latitude"] <= 90 or not -180 <= row["longitude"] <= 180:
            issues.append(
                Issue(
                    "error",
                    "point-coordinate-range",
                    "Point coordinate is out of range",
                    row["source_id"],
                    row["uid"],
                )
            )
    return issues


def _validate_airways(repository: AviationRepository) -> list[Issue]:
    issues: list[Issue] = []
    for row in repository.rows("SELECT uid, designator, source_id FROM airway"):
        if not row["designator"].strip():
            issues.append(
                Issue(
                    "error",
                    "airway-empty-designator",
                    "Airway designator is empty",
                    row["source_id"],
                    row["uid"],
                )
            )
        count = repository.scalar("SELECT COUNT(*) FROM airway_segment WHERE airway_uid = ?", (row["uid"],)) or 0
        if count == 0:
            issues.append(
                Issue(
                    "error",
                    "airway-no-segments",
                    f"{row['designator']} has no segments",
                    row["source_id"],
                    row["uid"],
                )
            )
    return issues


def _validate_segments(repository: AviationRepository) -> list[Issue]:
    issues: list[Issue] = []
    for row in repository.rows(
        """
        SELECT s.uid, s.source_id, s.from_point_uid, s.to_point_uid, s.distance_nm,
               f.latitude AS from_lat, f.longitude AS from_lon,
               t.latitude AS to_lat, t.longitude AS to_lon
        FROM airway_segment s
        LEFT JOIN nav_point f ON f.uid = s.from_point_uid
        LEFT JOIN nav_point t ON t.uid = s.to_point_uid
        """
    ):
        if row["from_point_uid"] == row["to_point_uid"]:
            issues.append(
                Issue("error", "segment-same-point", "Segment loops to itself", row["source_id"], row["uid"])
            )
        if row["from_lat"] is None or row["to_lat"] is None:
            issues.append(
                Issue(
                    "error",
                    "segment-missing-point",
                    "Segment references missing point",
                    row["source_id"],
                    row["uid"],
                )
            )
            continue
        distance = haversine_nm((row["from_lat"], row["from_lon"]), (row["to_lat"], row["to_lon"]))
        if distance <= 0.01:
            issues.append(
                Issue("error", "segment-zero-distance", "Segment distance is zero", row["source_id"], row["uid"])
            )
        if distance > 700:
            issues.append(
                Issue(
                    "warning",
                    "segment-long-distance",
                    f"Segment is {distance:.1f} NM",
                    row["source_id"],
                    row["uid"],
                )
            )
    return issues
