from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from aviationdb.models import Airport, Airway, AirwaySegment, Issue, NavPoint, SourceMetadata
from aviationdb.schema import SCHEMA_SQL


class AviationRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.connection.close()

    def init_schema(self) -> None:
        self.connection.executescript(SCHEMA_SQL)
        self.connection.commit()

    def reset_public_data(self) -> None:
        for table in [
            "validation_issue",
            "parse_issue",
            "procedure",
            "airway_segment",
            "airway",
            "nav_point",
            "airport",
            "source_metadata",
        ]:
            self.connection.execute(f"DELETE FROM {table}")
        self.connection.commit()

    def upsert_source(self, source: SourceMetadata) -> None:
        self.connection.execute(
            """
            INSERT INTO source_metadata (
              source_id, provider, country, source_url, source_type, airac_cycle, effective_date,
              retrieved_at, raw_file_sha256, license_url, redistribution_status, allow_app_bundle
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
              provider=excluded.provider,
              country=excluded.country,
              source_url=excluded.source_url,
              source_type=excluded.source_type,
              airac_cycle=excluded.airac_cycle,
              effective_date=excluded.effective_date,
              retrieved_at=excluded.retrieved_at,
              raw_file_sha256=excluded.raw_file_sha256,
              license_url=excluded.license_url,
              redistribution_status=excluded.redistribution_status,
              allow_app_bundle=excluded.allow_app_bundle
            """,
            (
                source.source_id,
                source.provider,
                source.country,
                source.source_url,
                source.source_type,
                source.airac_cycle,
                source.effective_date,
                source.retrieved_at,
                source.raw_file_sha256,
                source.license_url,
                source.redistribution_status,
                int(source.allow_app_bundle),
            ),
        )
        self.connection.commit()

    def insert_airports(self, airports: Iterable[Airport]) -> None:
        self.connection.executemany(
            """
            INSERT OR REPLACE INTO airport (
              uid, icao, iata, name, latitude, longitude, elevation_ft, country, fir, source_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.uid,
                    item.icao,
                    item.iata,
                    item.name,
                    item.latitude,
                    item.longitude,
                    item.elevation_ft,
                    item.country,
                    item.fir,
                    item.source_id,
                )
                for item in airports
            ],
        )
        self.connection.commit()

    def insert_nav_points(self, points: Iterable[NavPoint]) -> None:
        self.connection.executemany(
            """
            INSERT OR REPLACE INTO nav_point (
              uid, ident, name, latitude, longitude, point_type, usage_type, frequency, channel,
              country, fir, region_code, source_id, airac_cycle, effective_date, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.uid,
                    item.ident,
                    item.name,
                    item.latitude,
                    item.longitude,
                    item.point_type,
                    item.usage_type,
                    item.frequency,
                    item.channel,
                    item.country,
                    item.fir,
                    item.region_code,
                    item.source_id,
                    item.airac_cycle,
                    item.effective_date,
                    int(item.is_active),
                )
                for item in points
            ],
        )
        self.connection.commit()

    def insert_airways(self, airways: Iterable[Airway]) -> None:
        self.connection.executemany(
            """
            INSERT OR REPLACE INTO airway (
              uid, designator, route_type, direction, lower_limit_ft, upper_limit_ft,
              country, fir, source_id, airac_cycle, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.uid,
                    item.designator,
                    item.route_type,
                    item.direction,
                    item.lower_limit_ft,
                    item.upper_limit_ft,
                    item.country,
                    item.fir,
                    item.source_id,
                    item.airac_cycle,
                    int(item.is_active),
                )
                for item in airways
            ],
        )
        self.connection.commit()

    def insert_segments(self, segments: Iterable[AirwaySegment]) -> None:
        self.connection.executemany(
            """
            INSERT OR REPLACE INTO airway_segment (
              uid, airway_uid, sequence, from_point_uid, to_point_uid, distance_nm,
              initial_course_deg, reverse_course_deg, direction, minimum_altitude_ft,
              maximum_altitude_ft, source_id, airac_cycle
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.uid,
                    item.airway_uid,
                    item.sequence,
                    item.from_point_uid,
                    item.to_point_uid,
                    item.distance_nm,
                    item.initial_course_deg,
                    item.reverse_course_deg,
                    item.direction,
                    item.minimum_altitude_ft,
                    item.maximum_altitude_ft,
                    item.source_id,
                    item.airac_cycle,
                )
                for item in segments
            ],
        )
        self.connection.commit()

    def add_parse_issue(self, issue: Issue) -> None:
        self._add_issue("parse_issue", issue)

    def add_validation_issue(self, issue: Issue) -> None:
        self._add_issue("validation_issue", issue)

    def clear_validation_issues(self) -> None:
        self.connection.execute("DELETE FROM validation_issue")
        self.connection.commit()

    def _add_issue(self, table: str, issue: Issue) -> None:
        self.connection.execute(
            f"""
            INSERT INTO {table} (severity, code, message, source_id, entity_uid)
            VALUES (?, ?, ?, ?, ?)
            """,
            (issue.severity, issue.code, issue.message, issue.source_id, issue.entity_uid),
        )
        self.connection.commit()

    def rows(self, query: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return list(self.connection.execute(query, parameters))

    def scalar(self, query: str, parameters: tuple[Any, ...] = ()) -> Any:
        row = self.connection.execute(query, parameters).fetchone()
        return None if row is None else row[0]

