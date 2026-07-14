import Foundation
import SQLite3

final class TravelGlobeDatabase {
    private let configuredURL: URL?
    private var db: OpaquePointer?

    init(url: URL? = nil) {
        self.configuredURL = url
    }

    deinit {
        close()
    }

    func open() throws {
        if db != nil {
            return
        }
        let url = try databaseURL()
        if sqlite3_open(url.path, &db) != SQLITE_OK {
            throw DatabaseError.openFailed
        }
        try migrate()
    }

    func close() {
        sqlite3_close(db)
        db = nil
    }

    func execute(_ sql: String) throws {
        if sqlite3_exec(db, sql, nil, nil, nil) != SQLITE_OK {
            throw DatabaseError.executionFailed(String(cString: sqlite3_errmsg(db)))
        }
    }

    func connection() throws -> OpaquePointer {
        try open()
        guard let db else {
            throw DatabaseError.openFailed
        }
        return db
    }

    func errorMessage() -> String {
        guard let db else { return "Database is not open" }
        return String(cString: sqlite3_errmsg(db))
    }

    private func migrate() throws {
        try execute("""
        CREATE TABLE IF NOT EXISTS journeys (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL,
            status TEXT NOT NULL,
            segment_type TEXT NOT NULL,
            web_journey_id TEXT,
            web_segment_id TEXT,
            flight_number TEXT,
            origin_iata TEXT,
            destination_iata TEXT,
            aircraft_type TEXT,
            metadata_json TEXT
        );
        """)

        try? execute("ALTER TABLE journeys ADD COLUMN web_journey_id TEXT;")
        try? execute("ALTER TABLE journeys ADD COLUMN web_segment_id TEXT;")
        try? execute("ALTER TABLE journeys ADD COLUMN flight_number TEXT;")
        try? execute("ALTER TABLE journeys ADD COLUMN origin_iata TEXT;")
        try? execute("ALTER TABLE journeys ADD COLUMN destination_iata TEXT;")
        try? execute("ALTER TABLE journeys ADD COLUMN aircraft_type TEXT;")
        try? execute("ALTER TABLE journeys ADD COLUMN metadata_json TEXT;")

        try execute("""
        CREATE TABLE IF NOT EXISTS location_points (
            id TEXT PRIMARY KEY,
            journey_id TEXT NOT NULL,
            segment_id TEXT,
            timestamp REAL NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            altitude_meters REAL,
            speed_mps REAL,
            course_degrees REAL,
            horizontal_accuracy_meters REAL NOT NULL,
            vertical_accuracy_meters REAL,
            source TEXT NOT NULL
        );
        """)

        try execute("""
        CREATE INDEX IF NOT EXISTS idx_location_points_journey_time
        ON location_points (journey_id, timestamp);
        """)

        try execute("""
        CREATE TABLE IF NOT EXISTS visit_points (
            id TEXT PRIMARY KEY,
            journey_id TEXT NOT NULL,
            segment_id TEXT,
            timestamp REAL NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            altitude_meters REAL,
            horizontal_accuracy_meters REAL,
            title TEXT NOT NULL,
            note TEXT,
            source TEXT NOT NULL,
            source_id TEXT
        );
        """)

        try execute("""
        CREATE INDEX IF NOT EXISTS idx_visit_points_journey_time
        ON visit_points (journey_id, timestamp);
        """)

        try execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_visit_points_source
        ON visit_points (journey_id, source, source_id)
        WHERE source_id IS NOT NULL;
        """)
    }

    private func databaseURL() throws -> URL {
        if let configuredURL {
            try FileManager.default.createDirectory(
                at: configuredURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            return configuredURL
        }
        let directory = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        return directory.appendingPathComponent("TravelGlobe.sqlite")
    }
}

enum DatabaseError: Error {
    case openFailed
    case prepareFailed(String)
    case bindFailed(String)
    case stepFailed(String)
    case executionFailed(String)
}
