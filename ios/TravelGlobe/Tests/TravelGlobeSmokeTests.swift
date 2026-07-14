import XCTest
@testable import TravelGlobe

final class TravelGlobeSmokeTests: XCTestCase {
    func testJourneyRecordCodable() throws {
        let journey = JourneyRecord(
            id: UUID(),
            title: "Smoke",
            startTime: Date(timeIntervalSince1970: 0),
            status: .planned,
            segmentType: .flight
        )
        let data = try JSONEncoder().encode(journey)
        let decoded = try JSONDecoder().decode(JourneyRecord.self, from: data)
        XCTAssertEqual(decoded.title, "Smoke")
    }

    func testSQLiteJourneyRepositoryPersistsJourneyAndPoints() async throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension("sqlite")
        let repository = SQLiteJourneyRepository(database: TravelGlobeDatabase(url: url))
        let plan = FlightPlanRecord(
            webJourneyId: "journey-fd235",
            segmentId: "segment-fd235-2026-07-15",
            flightNumber: "FD235",
            originIata: "NRT",
            destinationIata: "KHH",
            departureTime: "2026-07-15T11:15:00.000Z",
            durationMinutes: 235,
            aircraftType: "A320",
            plannedRoute: []
        )
        let journey = try await repository.createJourney(title: "Persistence", segmentType: .flight, flightPlan: plan)
        let firstPoint = LocationPointRecord(
            id: UUID(),
            journeyId: journey.id,
            segmentId: plan.segmentId,
            timestamp: Date(timeIntervalSince1970: 100),
            latitude: 25.0797,
            longitude: 121.2342,
            altitudeMeters: 40,
            speedMetersPerSecond: 0,
            courseDegrees: 45,
            horizontalAccuracyMeters: 18,
            verticalAccuracyMeters: nil,
            source: "gps"
        )
        let secondPoint = LocationPointRecord(
            id: UUID(),
            journeyId: journey.id,
            segmentId: plan.segmentId,
            timestamp: Date(timeIntervalSince1970: 200),
            latitude: 35.5494,
            longitude: 139.7798,
            altitudeMeters: 6,
            speedMetersPerSecond: nil,
            courseDegrees: nil,
            horizontalAccuracyMeters: 16,
            verticalAccuracyMeters: nil,
            source: "gps"
        )

        try await repository.saveLocationPoint(secondPoint)
        try await repository.saveLocationPoint(firstPoint)
        try await repository.completeJourney(id: journey.id, endedAt: Date(timeIntervalSince1970: 300))

        let savedJourney = try await repository.journey(id: journey.id)
        let points = try await repository.locationPoints(journeyId: journey.id, since: nil)
        let pointCount = try await repository.locationPointCount(journeyId: journey.id)
        let recentPoints = try await repository.locationPoints(
            journeyId: journey.id,
            since: Date(timeIntervalSince1970: 150)
        )
        let recentJourneys = try await repository.recentJourneys(limit: 1)

        XCTAssertEqual(savedJourney?.status, .completed)
        XCTAssertEqual(savedJourney?.endTime, Date(timeIntervalSince1970: 300))
        XCTAssertEqual(savedJourney?.webJourneyId, plan.webJourneyId)
        XCTAssertEqual(savedJourney?.webSegmentId, plan.segmentId)
        XCTAssertEqual(savedJourney?.flightNumber, "FD235")
        XCTAssertEqual(points.map(\.segmentId), [plan.segmentId, plan.segmentId])
        XCTAssertEqual(pointCount, 2)
        XCTAssertEqual(points.map(\.id), [firstPoint.id, secondPoint.id])
        XCTAssertEqual(recentPoints.map(\.id), [secondPoint.id])
        XCTAssertEqual(recentJourneys.map(\.id), [journey.id])
    }
}
