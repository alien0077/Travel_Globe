import Foundation

struct JourneyRecord: Identifiable, Codable, Equatable {
    var id: UUID
    var title: String
    var startTime: Date
    var endTime: Date?
    var status: JourneyStatus
    var segmentType: JourneySegmentType
    var webJourneyId: String? = nil
    var webSegmentId: String? = nil
    var flightNumber: String? = nil
    var originIata: String? = nil
    var destinationIata: String? = nil
    var aircraftType: String? = nil
    var metadataJSON: String? = nil
}

enum JourneyStatus: String, Codable {
    case planned
    case recording
    case completed
    case archived
}

enum JourneySegmentType: String, Codable {
    case flight
    case walking
    case driving
    case train
    case cruise
    case manual
}

struct LocationPointRecord: Identifiable, Codable, Equatable {
    var id: UUID
    var journeyId: UUID
    var segmentId: String? = nil
    var timestamp: Date
    var latitude: Double
    var longitude: Double
    var altitudeMeters: Double?
    var speedMetersPerSecond: Double?
    var courseDegrees: Double?
    var horizontalAccuracyMeters: Double
    var verticalAccuracyMeters: Double?
    var source: String
}

struct VisitPointRecord: Identifiable, Codable, Equatable {
    var id: UUID
    var journeyId: UUID
    var segmentId: String? = nil
    var timestamp: Date
    var latitude: Double
    var longitude: Double
    var altitudeMeters: Double?
    var horizontalAccuracyMeters: Double?
    var title: String
    var note: String?
    var source: String
    var sourceId: String?
}

struct FlightPlanRecord: Codable, Equatable, Identifiable {
    var webJourneyId: String
    var segmentId: String
    var flightNumber: String
    var originIata: String
    var destinationIata: String
    var departureTime: String?
    var durationMinutes: Int?
    var aircraftType: String?
    var plannedRoute: [FlightPlanPointRecord]

    var id: String {
        selectionKey
    }

    var selectionKey: String {
        "\(webJourneyId)|\(segmentId)"
    }

    var displayTitle: String {
        "\(flightNumber) \(originIata) -> \(destinationIata)"
    }
}

struct FlightPlanPointRecord: Codable, Equatable {
    var timestamp: String
    var latitude: Double
    var longitude: Double
    var altitudeMeters: Double?
}
