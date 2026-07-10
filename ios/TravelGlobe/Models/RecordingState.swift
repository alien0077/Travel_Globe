import Foundation

enum RecordingState: String, Codable {
    case idle
    case requestingPermission
    case recording
    case paused
    case completed
    case failed
}

enum RecordingProfile: String, Codable {
    case flight
    case walking
    case driving
    case train
    case cruise
    case balanced
}

struct RecordingDiagnostic: Identifiable, Equatable {
    var id = UUID()
    var level: Level
    var message: String

    enum Level: String {
        case info
        case warning
        case error
    }

    static func error(_ message: String) -> RecordingDiagnostic {
        RecordingDiagnostic(level: .error, message: message)
    }
}
