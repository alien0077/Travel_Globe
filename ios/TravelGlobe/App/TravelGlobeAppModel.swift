import Foundation
import CoreLocation
import Photos
import UserNotifications

@MainActor
final class TravelGlobeAppModel: ObservableObject {
    @Published var activeJourney: JourneyRecord?
    @Published var recordingState: RecordingState = .idle
    @Published var diagnostics: [RecordingDiagnostic] = []
    @Published var activeLocationPointCount = 0
    @Published var storedJourneyCount = 0
    @Published var latestJourneySummary = "No stored journey"
    @Published var locationPermissionStatus = "Location: not checked"
    @Published var photoPermissionStatus = "Photos: not checked"
    @Published var notificationPermissionStatus = "Notifications: not checked"
    @Published var replayEngineStatus = "Replay Engine: not checked"
    @Published var latestLiveLocationMessage: NativeBridgeMessage?
    @Published var outboundBridgeMessages: [NativeBridgeMessage] = []
    @Published var pendingFlightPlan: FlightPlanRecord?
    @Published var recordingPlanStatus = "No flight plan applied"

    let locationRecorder: LocationRecorder
    let bridge = TravelGlobeBridge()
    let repository: JourneyRepository
    let exporter = JourneyExportService()
    private let photoImporter = PhotoImportService()
    private let notificationService = TravelNotificationService()

    init(
        repository: JourneyRepository = SQLiteJourneyRepository(database: TravelGlobeDatabase())
    ) {
        self.repository = repository
        self.locationRecorder = LocationRecorder(repository: repository)
        self.locationRecorder.onLocationUpdate = { [weak self] point in
            Task { @MainActor in
                self?.publishLiveLocation(point)
            }
        }
        self.bridge.onMessage = { [weak self] message in
            self?.handleWebMessage(message)
        }
        Task { await refreshDiagnostics() }
    }

    func startFlightRecording() async {
        do {
            let journey = try await repository.createJourney(
                title: "New Flight Recording",
                segmentType: .flight,
                flightPlan: pendingFlightPlan
            )
            activeJourney = journey
            recordingState = .recording
            activeLocationPointCount = 0
            try await locationRecorder.start(journeyId: journey.id, segmentId: journey.webSegmentId, profile: .flight)
            recordingPlanStatus = journey.flightNumber.map { "Recording \($0) \(journey.originIata ?? "") -> \(journey.destinationIata ?? "")" }
                ?? "Recording GPS-only flight"
            enqueueRecordingStatus("recording.started", journey: journey, points: nil)
            await refreshDiagnostics()
        } catch {
            diagnostics.append(.error("Unable to start recording: \(error.localizedDescription)"))
        }
    }

    func stopRecording() async {
        await locationRecorder.stop()
        recordingState = .completed
        if let activeJourney {
            let completedJourney = (try? await repository.journey(id: activeJourney.id)) ?? activeJourney
            let points = (try? await repository.locationPoints(journeyId: activeJourney.id, since: nil)) ?? []
            self.activeJourney = completedJourney
            activeLocationPointCount = points.count
            recordingPlanStatus = completedJourney.flightNumber.map { "Completed \($0) \(completedJourney.originIata ?? "") -> \(completedJourney.destinationIata ?? "")" }
                ?? "Completed GPS-only flight"
            enqueueRecordingStatus("recording.completed", journey: completedJourney, points: points)
        }
        await refreshDiagnostics()
    }

    func requestPhotoPermission() async {
        let status = await photoImporter.requestAuthorization()
        photoPermissionStatus = "Photos: \(Self.photoStatusText(status))"
        await refreshDiagnostics()
    }

    func requestNotificationPermission() async {
        do {
            try await notificationService.requestAuthorization()
            await refreshNotificationPermissionStatus()
            await refreshDiagnostics()
        } catch {
            notificationPermissionStatus = "Notifications: error \(error.localizedDescription)"
        }
    }

    func refreshDiagnostics() async {
        locationPermissionStatus = "Location: \(Self.locationStatusText(CLLocationManager.authorizationStatus()))"
        photoPermissionStatus = "Photos: \(Self.photoStatusText(PHPhotoLibrary.authorizationStatus(for: .readWrite)))"
        await refreshNotificationPermissionStatus()
        replayEngineStatus = "Replay Engine: \(Self.replayEngineIndexURL() == nil ? "missing index.html" : "index.html found")"

        do {
            let journeys = try await repository.recentJourneys(limit: 3)
            storedJourneyCount = journeys.count
            if let latest = journeys.first {
                activeJourney = activeJourney ?? latest
                let pointCount = try await repository.locationPointCount(journeyId: latest.id)
                activeLocationPointCount = pointCount
                latestJourneySummary = "\(latest.status.rawValue) | \(pointCount) GPS points | \(latest.id.uuidString.prefix(8))"
            } else {
                activeLocationPointCount = 0
                latestJourneySummary = "No stored journey"
            }
            diagnostics = [
                .info(locationPermissionStatus),
                .info(photoPermissionStatus),
                .info(notificationPermissionStatus),
                .info(replayEngineStatus),
                .info("Flight plan: \(recordingPlanStatus)"),
                .info("Stored journeys: \(storedJourneyCount)"),
                .info("Latest: \(latestJourneySummary)")
            ]
        } catch {
            diagnostics.append(.error("Unable to refresh diagnostics: \(error.localizedDescription)"))
        }
    }

    func updateReplayEngineStatus(_ status: String) {
        replayEngineStatus = "Replay Engine: \(status)"
    }

    private func publishLiveLocation(_ point: LocationPointRecord) {
        guard let payload = LiveLocationPayload(point: point).jsonString else { return }
        latestLiveLocationMessage = NativeBridgeMessage(
            version: "1.0",
            requestId: nil,
            type: "location.update",
            payload: payload
        )
        outboundBridgeMessages.append(latestLiveLocationMessage!)
    }

    private func handleWebMessage(_ message: NativeBridgeMessage) {
        switch message.type {
        case "flightPlan.apply":
            applyFlightPlanMessage(message)
        default:
            break
        }
    }

    private func applyFlightPlanMessage(_ message: NativeBridgeMessage) {
        guard
            let data = message.payload.data(using: .utf8),
            let plan = try? JSONDecoder().decode(FlightPlanRecord.self, from: data)
        else {
            diagnostics.append(.error("Unable to decode flight plan from Replay Engine"))
            return
        }
        pendingFlightPlan = plan
        recordingPlanStatus = "Ready \(plan.flightNumber) \(plan.originIata) -> \(plan.destinationIata)"
        enqueueBridgeMessage(type: "flightPlan.ready", payload: FlightPlanStatusPayload(plan: plan))
    }

    private func enqueueRecordingStatus(_ type: String, journey: JourneyRecord, points: [LocationPointRecord]?) {
        enqueueBridgeMessage(
            type: type,
            payload: RecordingStatusPayload(journey: journey, points: points)
        )
    }

    private func enqueueBridgeMessage<T: Encodable>(type: String, payload: T) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        guard
            let data = try? encoder.encode(payload),
            let json = String(data: data, encoding: .utf8)
        else {
            return
        }
        outboundBridgeMessages.append(
            NativeBridgeMessage(
                version: "1.0",
                requestId: nil,
                type: type,
                payload: json
            )
        )
    }

    private func refreshNotificationPermissionStatus() async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        notificationPermissionStatus = "Notifications: \(Self.notificationStatusText(settings.authorizationStatus))"
    }

    static func replayEngineIndexURL() -> URL? {
        Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "ReplayEngine")
            ?? Bundle.main.url(forResource: "index", withExtension: "html")
    }

    private static func locationStatusText(_ status: CLAuthorizationStatus) -> String {
        switch status {
        case .notDetermined:
            return "not determined"
        case .restricted:
            return "restricted"
        case .denied:
            return "denied"
        case .authorizedAlways:
            return "always"
        case .authorizedWhenInUse:
            return "when in use"
        @unknown default:
            return "unknown"
        }
    }

    private static func photoStatusText(_ status: PHAuthorizationStatus) -> String {
        switch status {
        case .notDetermined:
            return "not determined"
        case .restricted:
            return "restricted"
        case .denied:
            return "denied"
        case .authorized:
            return "authorized"
        case .limited:
            return "limited"
        @unknown default:
            return "unknown"
        }
    }

    private static func notificationStatusText(_ status: UNAuthorizationStatus) -> String {
        switch status {
        case .notDetermined:
            return "not determined"
        case .denied:
            return "denied"
        case .authorized:
            return "authorized"
        case .provisional:
            return "provisional"
        case .ephemeral:
            return "ephemeral"
        @unknown default:
            return "unknown"
        }
    }
}

private struct FlightPlanStatusPayload: Encodable {
    var webJourneyId: String
    var segmentId: String
    var flightNumber: String
    var originIata: String
    var destinationIata: String
    var aircraftType: String?
    var status: String

    init(plan: FlightPlanRecord) {
        webJourneyId = plan.webJourneyId
        segmentId = plan.segmentId
        flightNumber = plan.flightNumber
        originIata = plan.originIata
        destinationIata = plan.destinationIata
        aircraftType = plan.aircraftType
        status = "ready"
    }
}

private struct RecordingStatusPayload: Encodable {
    var nativeJourneyId: String
    var webJourneyId: String?
    var segmentId: String?
    var flightNumber: String?
    var originIata: String?
    var destinationIata: String?
    var aircraftType: String?
    var status: String
    var startedAt: String
    var endedAt: String?
    var points: [LiveLocationPayload]?

    init(journey: JourneyRecord, points: [LocationPointRecord]?) {
        nativeJourneyId = journey.id.uuidString
        webJourneyId = journey.webJourneyId
        segmentId = journey.webSegmentId
        flightNumber = journey.flightNumber
        originIata = journey.originIata
        destinationIata = journey.destinationIata
        aircraftType = journey.aircraftType
        status = journey.status.rawValue
        startedAt = LiveLocationPayload.timestampFormatter.string(from: journey.startTime)
        endedAt = journey.endTime.map { LiveLocationPayload.timestampFormatter.string(from: $0) }
        self.points = points?.map(LiveLocationPayload.init(point:))
    }
}

private struct LiveLocationPayload: Encodable {
    var timestamp: String
    var latitude: Double
    var longitude: Double
    var altitudeMeters: Double?
    var speedMetersPerSecond: Double?
    var courseDegrees: Double?
    var horizontalAccuracyMeters: Double
    var verticalAccuracyMeters: Double?
    var source = "gps"

    init(point: LocationPointRecord) {
        timestamp = Self.timestampFormatter.string(from: point.timestamp)
        latitude = point.latitude
        longitude = point.longitude
        altitudeMeters = point.altitudeMeters
        speedMetersPerSecond = point.speedMetersPerSecond
        courseDegrees = point.courseDegrees
        horizontalAccuracyMeters = point.horizontalAccuracyMeters
        verticalAccuracyMeters = point.verticalAccuracyMeters
    }

    var jsonString: String? {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        guard let data = try? encoder.encode(self) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private enum CodingKeys: String, CodingKey {
        case timestamp
        case latitude
        case longitude
        case altitudeMeters
        case speedMetersPerSecond
        case courseDegrees
        case horizontalAccuracyMeters
        case verticalAccuracyMeters
        case source
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(timestamp, forKey: .timestamp)
        try container.encode(latitude, forKey: .latitude)
        try container.encode(longitude, forKey: .longitude)
        try encodeNullable(altitudeMeters, forKey: .altitudeMeters, into: &container)
        try encodeNullable(speedMetersPerSecond, forKey: .speedMetersPerSecond, into: &container)
        try encodeNullable(courseDegrees, forKey: .courseDegrees, into: &container)
        try container.encode(horizontalAccuracyMeters, forKey: .horizontalAccuracyMeters)
        try encodeNullable(verticalAccuracyMeters, forKey: .verticalAccuracyMeters, into: &container)
        try container.encode(source, forKey: .source)
    }

    private func encodeNullable(
        _ value: Double?,
        forKey key: CodingKeys,
        into container: inout KeyedEncodingContainer<CodingKeys>
    ) throws {
        if let value {
            try container.encode(value, forKey: key)
        } else {
            try container.encodeNil(forKey: key)
        }
    }

    static let timestampFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
}
