import Foundation

struct JourneyExportService {
    func exportJSON(journey: JourneyRecord, points: [LocationPointRecord]) throws -> Data {
        let payload = PortableJourneyPayload(journey: journey, points: points)
        return try JSONEncoder().encode(payload)
    }
}

struct PortableJourneyPayload: Codable {
    var schemaVersion = "1.0.0"
    var appVersion = "0.1.0"
    var journey: JourneyRecord
    var points: [LocationPointRecord]
}
