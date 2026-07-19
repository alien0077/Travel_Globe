from __future__ import annotations

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source_metadata (
    source_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    country TEXT,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    airac_cycle TEXT,
    effective_date TEXT,
    retrieved_at TEXT NOT NULL,
    raw_file_sha256 TEXT NOT NULL,
    license_url TEXT,
    redistribution_status TEXT NOT NULL,
    allow_app_bundle INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS airport (
    uid TEXT PRIMARY KEY,
    icao TEXT,
    iata TEXT,
    name TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    elevation_ft INTEGER,
    country TEXT,
    fir TEXT,
    source_id TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES source_metadata(source_id)
);

CREATE TABLE IF NOT EXISTS nav_point (
    uid TEXT PRIMARY KEY,
    ident TEXT NOT NULL,
    name TEXT,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    point_type TEXT NOT NULL,
    usage_type TEXT,
    frequency REAL,
    channel TEXT,
    country TEXT,
    fir TEXT,
    region_code TEXT,
    source_id TEXT NOT NULL,
    airac_cycle TEXT,
    effective_date TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (source_id) REFERENCES source_metadata(source_id)
);

CREATE TABLE IF NOT EXISTS airway (
    uid TEXT PRIMARY KEY,
    designator TEXT NOT NULL,
    route_type TEXT,
    direction TEXT,
    lower_limit_ft INTEGER,
    upper_limit_ft INTEGER,
    country TEXT,
    fir TEXT,
    source_id TEXT NOT NULL,
    airac_cycle TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (source_id) REFERENCES source_metadata(source_id)
);

CREATE TABLE IF NOT EXISTS airway_segment (
    uid TEXT PRIMARY KEY,
    airway_uid TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    from_point_uid TEXT NOT NULL,
    to_point_uid TEXT NOT NULL,
    distance_nm REAL,
    initial_course_deg REAL,
    reverse_course_deg REAL,
    direction TEXT,
    minimum_altitude_ft INTEGER,
    maximum_altitude_ft INTEGER,
    source_id TEXT NOT NULL,
    airac_cycle TEXT,
    FOREIGN KEY (airway_uid) REFERENCES airway(uid),
    FOREIGN KEY (from_point_uid) REFERENCES nav_point(uid),
    FOREIGN KEY (to_point_uid) REFERENCES nav_point(uid),
    FOREIGN KEY (source_id) REFERENCES source_metadata(source_id)
);

CREATE TABLE IF NOT EXISTS procedure (
    uid TEXT PRIMARY KEY,
    airport_uid TEXT,
    procedure_type TEXT NOT NULL,
    designator TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_id TEXT NOT NULL,
    FOREIGN KEY (airport_uid) REFERENCES airport(uid),
    FOREIGN KEY (source_id) REFERENCES source_metadata(source_id)
);

CREATE TABLE IF NOT EXISTS parse_issue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    source_id TEXT,
    entity_uid TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS validation_issue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    source_id TEXT,
    entity_uid TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_airport_iata ON airport(iata);
CREATE INDEX IF NOT EXISTS idx_airport_icao ON airport(icao);
CREATE INDEX IF NOT EXISTS idx_nav_point_ident ON nav_point(ident);
CREATE INDEX IF NOT EXISTS idx_nav_point_country ON nav_point(country);
CREATE INDEX IF NOT EXISTS idx_nav_point_location ON nav_point(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_airway_designator ON airway(designator);
CREATE INDEX IF NOT EXISTS idx_segment_airway_sequence ON airway_segment(airway_uid, sequence);
CREATE INDEX IF NOT EXISTS idx_segment_from ON airway_segment(from_point_uid);
CREATE INDEX IF NOT EXISTS idx_segment_to ON airway_segment(to_point_uid);
"""

