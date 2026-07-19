from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

REDISTRIBUTION_ALLOWED = "redistribution_allowed"


@dataclass(frozen=True)
class SourceMetadata:
    source_id: str
    provider: str
    country: str | None
    source_url: str
    source_type: str
    raw_file_sha256: str
    license_url: str | None = None
    redistribution_status: str = "unknown"
    airac_cycle: str | None = None
    effective_date: str | None = None
    retrieved_at: str = ""
    allow_app_bundle: bool = False

    def with_retrieved_now(self) -> SourceMetadata:
        return SourceMetadata(
            **{
                **self.__dict__,
                "retrieved_at": self.retrieved_at or datetime.now(UTC).isoformat(),
            }
        )


@dataclass(frozen=True)
class Airport:
    uid: str
    icao: str | None
    iata: str | None
    name: str
    latitude: float
    longitude: float
    country: str | None
    source_id: str
    elevation_ft: int | None = None
    fir: str | None = None


@dataclass(frozen=True)
class NavPoint:
    uid: str
    ident: str
    latitude: float
    longitude: float
    point_type: str
    source_id: str
    name: str | None = None
    country: str | None = None
    fir: str | None = None
    region_code: str | None = None
    usage_type: str | None = None
    frequency: float | None = None
    channel: str | None = None
    airac_cycle: str | None = None
    effective_date: str | None = None
    is_active: bool = True


@dataclass(frozen=True)
class Airway:
    uid: str
    designator: str
    source_id: str
    route_type: str | None = None
    direction: str | None = None
    lower_limit_ft: int | None = None
    upper_limit_ft: int | None = None
    country: str | None = None
    fir: str | None = None
    airac_cycle: str | None = None
    is_active: bool = True


@dataclass(frozen=True)
class AirwaySegment:
    uid: str
    airway_uid: str
    sequence: int
    from_point_uid: str
    to_point_uid: str
    source_id: str
    distance_nm: float | None = None
    initial_course_deg: float | None = None
    reverse_course_deg: float | None = None
    direction: str | None = None
    minimum_altitude_ft: int | None = None
    maximum_altitude_ft: int | None = None
    airac_cycle: str | None = None


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str
    source_id: str | None = None
    entity_uid: str | None = None

