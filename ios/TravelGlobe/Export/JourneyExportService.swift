import Foundation

struct JourneyExportService {
    func exportJSON(
        journey: JourneyRecord,
        points: [LocationPointRecord],
        visitPoints: [VisitPointRecord] = []
    ) throws -> Data {
        let payload = PortableJourneyPayload(journey: journey, points: points, visitPoints: visitPoints)
        return try JSONEncoder().encode(payload)
    }
}

struct PortableJourneyPayload: Codable {
    var schemaVersion = "1.0.0"
    var appVersion = "0.1.0"
    var journey: JourneyRecord
    var points: [LocationPointRecord]
    var visitPoints: [VisitPointRecord] = []
}
