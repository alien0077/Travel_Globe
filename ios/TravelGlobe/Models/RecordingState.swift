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

enum FlightMode: String, CaseIterable, Codable {
    case live
    case simulation

    var label: String {
        switch self {
        case .live:
            return "Live GPS"
        case .simulation:
            return "模擬航線"
        }
    }
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

    static func info(_ message: String) -> RecordingDiagnostic {
        RecordingDiagnostic(level: .info, message: message)
    }

    static func error(_ message: String) -> RecordingDiagnostic {
        RecordingDiagnostic(level: .error, message: message)
    }
}
