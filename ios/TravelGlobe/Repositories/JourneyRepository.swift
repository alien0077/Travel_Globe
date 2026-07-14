import Foundation

protocol JourneyRepository {
    func createJourney(title: String, segmentType: JourneySegmentType, flightPlan: FlightPlanRecord?) async throws -> JourneyRecord
    func saveLocationPoint(_ point: LocationPointRecord) async throws
    func locationPoints(journeyId: UUID, since: Date?) async throws -> [LocationPointRecord]
    func locationPointCount(journeyId: UUID) async throws -> Int
    func recentJourneys(limit: Int) async throws -> [JourneyRecord]
    func completeJourney(id: UUID, endedAt: Date) async throws
    func journey(id: UUID) async throws -> JourneyRecord?
}

extension JourneyRepository {
    func createJourney(title: String, segmentType: JourneySegmentType) async throws -> JourneyRecord {
        try await createJourney(title: title, segmentType: segmentType, flightPlan: nil)
    }
}
