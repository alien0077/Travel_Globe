import Foundation

protocol JourneyRepository {
    func createJourney(title: String, segmentType: JourneySegmentType) async throws -> JourneyRecord
    func saveLocationPoint(_ point: LocationPointRecord) async throws
    func locationPoints(journeyId: UUID, since: Date?) async throws -> [LocationPointRecord]
    func completeJourney(id: UUID, endedAt: Date) async throws
}
