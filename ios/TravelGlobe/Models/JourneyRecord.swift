import Foundation

struct JourneyRecord: Identifiable, Codable, Equatable {
    var id: UUID
    var title: String
    var startTime: Date
    var endTime: Date?
    var status: JourneyStatus
    var segmentType: JourneySegmentType
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
    var segmentId: UUID?
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
