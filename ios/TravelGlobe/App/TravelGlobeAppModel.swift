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
        Task { await refreshDiagnostics() }
    }

    func startFlightRecording() async {
        do {
            let journey = try await repository.createJourney(title: "New Flight Recording", segmentType: .flight)
            activeJourney = journey
            recordingState = .recording
            activeLocationPointCount = 0
            try await locationRecorder.start(journeyId: journey.id, profile: .flight)
            await refreshDiagnostics()
        } catch {
            diagnostics.append(.error("Unable to start recording: \(error.localizedDescription)"))
        }
    }

    func stopRecording() async {
        await locationRecorder.stop()
        recordingState = .completed
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
                .info("Stored journeys: \(storedJourneyCount)"),
                .info("Latest: \(latestJourneySummary)")
            ]
        } catch {
            diagnostics.append(.error("Unable to refresh diagnostics: \(error.localizedDescription)"))
        }
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
