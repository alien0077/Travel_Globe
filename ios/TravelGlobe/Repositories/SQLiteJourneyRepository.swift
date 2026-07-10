import Foundation

actor SQLiteJourneyRepository: JourneyRepository {
    private let database: TravelGlobeDatabase
    private var inMemoryJourneys: [UUID: JourneyRecord] = [:]
    private var inMemoryPoints: [UUID: [LocationPointRecord]] = [:]

    init(database: TravelGlobeDatabase) {
        self.database = database
        try? database.open()
    }

    func createJourney(title: String, segmentType: JourneySegmentType) async throws -> JourneyRecord {
        let journey = JourneyRecord(
            id: UUID(),
            title: title,
            startTime: Date(),
            status: .recording,
            segmentType: segmentType
        )
        inMemoryJourneys[journey.id] = journey
        return journey
    }

    func saveLocationPoint(_ point: LocationPointRecord) async throws {
        inMemoryPoints[point.journeyId, default: []].append(point)
    }

    func locationPoints(journeyId: UUID, since: Date?) async throws -> [LocationPointRecord] {
        let points = inMemoryPoints[journeyId, default: []]
        guard let since else { return points }
        return points.filter { $0.timestamp > since }
    }

    func completeJourney(id: UUID, endedAt: Date) async throws {
        guard var journey = inMemoryJourneys[id] else { return }
        journey.status = .completed
        journey.endTime = endedAt
        inMemoryJourneys[id] = journey
    }
}
