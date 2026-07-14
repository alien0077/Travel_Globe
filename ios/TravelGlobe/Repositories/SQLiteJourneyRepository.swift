import Foundation
import SQLite3

actor SQLiteJourneyRepository: JourneyRepository {
    private let database: TravelGlobeDatabase
    private let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    init(database: TravelGlobeDatabase) {
        self.database = database
    }

    func createJourney(title: String, segmentType: JourneySegmentType, flightPlan: FlightPlanRecord?) async throws -> JourneyRecord {
        let journey = JourneyRecord(
            id: UUID(),
            title: flightPlan?.displayTitle ?? title,
            startTime: Date(),
            status: .recording,
            segmentType: segmentType,
            webJourneyId: flightPlan?.webJourneyId,
            webSegmentId: flightPlan?.segmentId,
            flightNumber: flightPlan?.flightNumber,
            originIata: flightPlan?.originIata,
            destinationIata: flightPlan?.destinationIata,
            aircraftType: flightPlan?.aircraftType,
            metadataJSON: flightPlan.flatMap(Self.encodeMetadataJSON)
        )
        let db = try database.connection()
        let statement = try prepare("""
        INSERT INTO journeys (
            id, title, start_time, end_time, status, segment_type,
            web_journey_id, web_segment_id, flight_number, origin_iata,
            destination_iata, aircraft_type, metadata_json
        )
        VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, db: db)
        defer { sqlite3_finalize(statement) }

        try bindText(journey.id.uuidString, at: 1, statement: statement)
        try bindText(journey.title, at: 2, statement: statement)
        try bindDouble(journey.startTime.timeIntervalSince1970, at: 3, statement: statement)
        try bindText(journey.status.rawValue, at: 4, statement: statement)
        try bindText(journey.segmentType.rawValue, at: 5, statement: statement)
        try bindOptionalText(journey.webJourneyId, at: 6, statement: statement)
        try bindOptionalText(journey.webSegmentId, at: 7, statement: statement)
        try bindOptionalText(journey.flightNumber, at: 8, statement: statement)
        try bindOptionalText(journey.originIata, at: 9, statement: statement)
        try bindOptionalText(journey.destinationIata, at: 10, statement: statement)
        try bindOptionalText(journey.aircraftType, at: 11, statement: statement)
        try bindOptionalText(journey.metadataJSON, at: 12, statement: statement)
        try stepDone(statement)
        return journey
    }

    func saveLocationPoint(_ point: LocationPointRecord) async throws {
        let db = try database.connection()
        let statement = try prepare("""
        INSERT OR REPLACE INTO location_points (
            id, journey_id, segment_id, timestamp, latitude, longitude,
            altitude_meters, speed_mps, course_degrees,
            horizontal_accuracy_meters, vertical_accuracy_meters, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, db: db)
        defer { sqlite3_finalize(statement) }

        try bindText(point.id.uuidString, at: 1, statement: statement)
        try bindText(point.journeyId.uuidString, at: 2, statement: statement)
        try bindOptionalText(point.segmentId, at: 3, statement: statement)
        try bindDouble(point.timestamp.timeIntervalSince1970, at: 4, statement: statement)
        try bindDouble(point.latitude, at: 5, statement: statement)
        try bindDouble(point.longitude, at: 6, statement: statement)
        try bindOptionalDouble(point.altitudeMeters, at: 7, statement: statement)
        try bindOptionalDouble(point.speedMetersPerSecond, at: 8, statement: statement)
        try bindOptionalDouble(point.courseDegrees, at: 9, statement: statement)
        try bindDouble(point.horizontalAccuracyMeters, at: 10, statement: statement)
        try bindOptionalDouble(point.verticalAccuracyMeters, at: 11, statement: statement)
        try bindText(point.source, at: 12, statement: statement)
        try stepDone(statement)
    }

    func locationPoints(journeyId: UUID, since: Date?) async throws -> [LocationPointRecord] {
        let db = try database.connection()
        let sql: String
        if since == nil {
            sql = """
            SELECT id, journey_id, segment_id, timestamp, latitude, longitude,
                   altitude_meters, speed_mps, course_degrees,
                   horizontal_accuracy_meters, vertical_accuracy_meters, source
            FROM location_points
            WHERE journey_id = ?
            ORDER BY timestamp ASC;
            """
        } else {
            sql = """
            SELECT id, journey_id, segment_id, timestamp, latitude, longitude,
                   altitude_meters, speed_mps, course_degrees,
                   horizontal_accuracy_meters, vertical_accuracy_meters, source
            FROM location_points
            WHERE journey_id = ? AND timestamp > ?
            ORDER BY timestamp ASC;
            """
        }
        let statement = try prepare(sql, db: db)
        defer { sqlite3_finalize(statement) }

        try bindText(journeyId.uuidString, at: 1, statement: statement)
        if let since {
            try bindDouble(since.timeIntervalSince1970, at: 2, statement: statement)
        }

        var points: [LocationPointRecord] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            points.append(try decodePoint(statement))
        }
        return points
    }

    func locationPointCount(journeyId: UUID) async throws -> Int {
        let db = try database.connection()
        let statement = try prepare("""
        SELECT COUNT(*)
        FROM location_points
        WHERE journey_id = ?;
        """, db: db)
        defer { sqlite3_finalize(statement) }

        try bindText(journeyId.uuidString, at: 1, statement: statement)
        guard sqlite3_step(statement) == SQLITE_ROW else {
            throw DatabaseError.stepFailed(database.errorMessage())
        }
        return Int(sqlite3_column_int(statement, 0))
    }

    func recentJourneys(limit: Int) async throws -> [JourneyRecord] {
        let db = try database.connection()
        let statement = try prepare("""
        SELECT id, title, start_time, end_time, status, segment_type,
               web_journey_id, web_segment_id, flight_number, origin_iata,
               destination_iata, aircraft_type, metadata_json
        FROM journeys
        ORDER BY start_time DESC
        LIMIT ?;
        """, db: db)
        defer { sqlite3_finalize(statement) }

        sqlite3_bind_int(statement, 1, Int32(max(1, limit)))

        var journeys: [JourneyRecord] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            journeys.append(try decodeJourney(statement))
        }
        return journeys
    }

    func completeJourney(id: UUID, endedAt: Date) async throws {
        let db = try database.connection()
        let statement = try prepare("""
        UPDATE journeys
        SET status = ?, end_time = ?
        WHERE id = ?;
        """, db: db)
        defer { sqlite3_finalize(statement) }

        try bindText(JourneyStatus.completed.rawValue, at: 1, statement: statement)
        try bindDouble(endedAt.timeIntervalSince1970, at: 2, statement: statement)
        try bindText(id.uuidString, at: 3, statement: statement)
        try stepDone(statement)
    }

    func journey(id: UUID) async throws -> JourneyRecord? {
        let db = try database.connection()
        let statement = try prepare("""
        SELECT id, title, start_time, end_time, status, segment_type,
               web_journey_id, web_segment_id, flight_number, origin_iata,
               destination_iata, aircraft_type, metadata_json
        FROM journeys
        WHERE id = ?;
        """, db: db)
        defer { sqlite3_finalize(statement) }

        try bindText(id.uuidString, at: 1, statement: statement)
        guard sqlite3_step(statement) == SQLITE_ROW else {
            return nil
        }
        return try decodeJourney(statement)
    }

    private func prepare(_ sql: String, db: OpaquePointer) throws -> OpaquePointer {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &statement, nil) == SQLITE_OK, let statement else {
            throw DatabaseError.prepareFailed(database.errorMessage())
        }
        return statement
    }

    private func bindText(_ value: String, at index: Int32, statement: OpaquePointer) throws {
        guard sqlite3_bind_text(statement, index, value, -1, transient) == SQLITE_OK else {
            throw DatabaseError.bindFailed(database.errorMessage())
        }
    }

    private func bindOptionalText(_ value: String?, at index: Int32, statement: OpaquePointer) throws {
        guard let value else {
            sqlite3_bind_null(statement, index)
            return
        }
        try bindText(value, at: index, statement: statement)
    }

    private func bindDouble(_ value: Double, at index: Int32, statement: OpaquePointer) throws {
        guard sqlite3_bind_double(statement, index, value) == SQLITE_OK else {
            throw DatabaseError.bindFailed(database.errorMessage())
        }
    }

    private func bindOptionalDouble(_ value: Double?, at index: Int32, statement: OpaquePointer) throws {
        guard let value else {
            sqlite3_bind_null(statement, index)
            return
        }
        try bindDouble(value, at: index, statement: statement)
    }

    private func stepDone(_ statement: OpaquePointer) throws {
        guard sqlite3_step(statement) == SQLITE_DONE else {
            throw DatabaseError.stepFailed(database.errorMessage())
        }
    }

    private func decodeJourney(_ statement: OpaquePointer) throws -> JourneyRecord {
        guard
            let id = UUID(uuidString: try textColumn(0, statement: statement)),
            let status = JourneyStatus(rawValue: try textColumn(4, statement: statement)),
            let segmentType = JourneySegmentType(rawValue: try textColumn(5, statement: statement))
        else {
            throw DatabaseError.stepFailed("Unable to decode journey row")
        }
        let endTime = sqlite3_column_type(statement, 3) == SQLITE_NULL
            ? nil
            : Date(timeIntervalSince1970: sqlite3_column_double(statement, 3))
        return JourneyRecord(
            id: id,
            title: try textColumn(1, statement: statement),
            startTime: Date(timeIntervalSince1970: sqlite3_column_double(statement, 2)),
            endTime: endTime,
            status: status,
            segmentType: segmentType,
            webJourneyId: try optionalTextColumn(6, statement: statement),
            webSegmentId: try optionalTextColumn(7, statement: statement),
            flightNumber: try optionalTextColumn(8, statement: statement),
            originIata: try optionalTextColumn(9, statement: statement),
            destinationIata: try optionalTextColumn(10, statement: statement),
            aircraftType: try optionalTextColumn(11, statement: statement),
            metadataJSON: try optionalTextColumn(12, statement: statement)
        )
    }

    private func decodePoint(_ statement: OpaquePointer) throws -> LocationPointRecord {
        guard
            let id = UUID(uuidString: try textColumn(0, statement: statement)),
            let journeyId = UUID(uuidString: try textColumn(1, statement: statement))
        else {
            throw DatabaseError.stepFailed("Unable to decode location point row")
        }
        return LocationPointRecord(
            id: id,
            journeyId: journeyId,
            segmentId: try optionalTextColumn(2, statement: statement),
            timestamp: Date(timeIntervalSince1970: sqlite3_column_double(statement, 3)),
            latitude: sqlite3_column_double(statement, 4),
            longitude: sqlite3_column_double(statement, 5),
            altitudeMeters: optionalDoubleColumn(6, statement: statement),
            speedMetersPerSecond: optionalDoubleColumn(7, statement: statement),
            courseDegrees: optionalDoubleColumn(8, statement: statement),
            horizontalAccuracyMeters: sqlite3_column_double(statement, 9),
            verticalAccuracyMeters: optionalDoubleColumn(10, statement: statement),
            source: try textColumn(11, statement: statement)
        )
    }

    private func textColumn(_ index: Int32, statement: OpaquePointer) throws -> String {
        guard let value = sqlite3_column_text(statement, index) else {
            throw DatabaseError.stepFailed("Expected non-null text column \(index)")
        }
        return String(cString: value)
    }

    private func optionalTextColumn(_ index: Int32, statement: OpaquePointer) throws -> String? {
        guard sqlite3_column_type(statement, index) != SQLITE_NULL else {
            return nil
        }
        return try textColumn(index, statement: statement)
    }

    private func optionalDoubleColumn(_ index: Int32, statement: OpaquePointer) -> Double? {
        sqlite3_column_type(statement, index) == SQLITE_NULL ? nil : sqlite3_column_double(statement, index)
    }

    private static func encodeMetadataJSON(_ flightPlan: FlightPlanRecord) -> String? {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        guard
            let data = try? encoder.encode(flightPlan),
            let json = String(data: data, encoding: .utf8)
        else {
            return nil
        }
        return json
    }
}
