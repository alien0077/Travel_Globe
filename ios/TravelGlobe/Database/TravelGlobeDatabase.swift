import Foundation
import SQLite3

final class TravelGlobeDatabase {
    private var db: OpaquePointer?

    func open() throws {
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

    private func migrate() throws {
        try execute("""
        CREATE TABLE IF NOT EXISTS journeys (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL,
            status TEXT NOT NULL,
            segment_type TEXT NOT NULL
        );
        """)

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
    }

    private func databaseURL() throws -> URL {
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
    case executionFailed(String)
}
