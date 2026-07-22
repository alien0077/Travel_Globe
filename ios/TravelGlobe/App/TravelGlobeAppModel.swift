import Foundation
import CoreLocation
import Photos
import UIKit
import UserNotifications

@MainActor
final class TravelGlobeAppModel: ObservableObject {
    @Published var activeJourney: JourneyRecord?
    @Published var recordingState: RecordingState = .idle
    @Published var diagnostics: [RecordingDiagnostic] = []
    @Published var activeLocationPointCount = 0
    @Published var activeVisitPointCount = 0
    @Published var storedJourneyCount = 0
    @Published var latestJourneySummary = "No stored journey"
    @Published var locationPermissionStatus = "Location: not checked"
    @Published var photoPermissionStatus = "Photos: not checked"
    @Published var notificationPermissionStatus = "Notifications: not checked"
    @Published var replayEngineStatus = "Replay Engine: not checked"
    @Published var offlinePackUpdateStatus = "Offline data: not checked"
    @Published var latestLiveLocationMessage: NativeBridgeMessage?
    @Published var outboundBridgeMessages: [NativeBridgeMessage] = []
    @Published var pendingFlightPlan: FlightPlanRecord?
    @Published var flightPlans: [FlightPlanRecord] = []
    @Published var selectedFlightPlanKey = ""
    @Published var recordingPlanStatus = "No flight plan applied"
    @Published var visitPointStatus = "No visit points"

    let locationRecorder: LocationRecorder
    let bridge = TravelGlobeBridge()
    let repository: JourneyRepository
    let exporter = JourneyExportService()
    private let photoImporter = PhotoImportService()
    private let notificationService = TravelNotificationService()
    private let offlinePackDownloadService = OfflinePackDownloadService()
    private var lastOfflinePackUpdateCheck: Date?

    init(
        repository: JourneyRepository = SQLiteJourneyRepository(database: TravelGlobeDatabase())
    ) {
        self.repository = repository
        self.locationRecorder = LocationRecorder(repository: repository)
        self.flightPlans = Self.loadStoredFlightPlans()
        self.selectedFlightPlanKey = Self.loadSelectedFlightPlanKey()
        if let selected = flightPlans.first(where: { $0.selectionKey == selectedFlightPlanKey }) ?? flightPlans.first {
            pendingFlightPlan = selected
            selectedFlightPlanKey = selected.selectionKey
            recordingPlanStatus = "Selected \(selected.flightNumber) \(selected.originIata) -> \(selected.destinationIata)"
        }
        self.locationRecorder.onLocationUpdate = { [weak self] point in
            Task { @MainActor in
                self?.publishLiveLocation(point)
            }
        }
        self.bridge.onMessage = { [weak self] message in
            self?.handleWebMessage(message)
        }
        Task {
            await refreshDiagnostics()
            await checkForOfflinePackUpdates()
        }
    }

    func startFlightRecording() async {
        do {
            let journey = try await repository.createJourney(
                title: "New Flight Recording",
                segmentType: .flight,
                flightPlan: selectedFlightPlan
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
            let visitPoints = (try? await repository.visitPoints(journeyId: activeJourney.id)) ?? []
            self.activeJourney = completedJourney
            activeLocationPointCount = points.count
            activeVisitPointCount = visitPoints.count
            recordingPlanStatus = completedJourney.flightNumber.map { "Completed \($0) \(completedJourney.originIata ?? "") -> \(completedJourney.destinationIata ?? "")" }
                ?? "Completed GPS-only flight"
            enqueueRecordingStatus("recording.completed", journey: completedJourney, points: points)
            enqueueVisitPointsStatus("visitPoints.sync", journey: completedJourney, points: visitPoints)
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

    func addCurrentGPSVisitPoint() async {
        do {
            guard let journey = try await targetJourneyForVisitPoint() else {
                visitPointStatus = "No journey available for visit point"
                return
            }
            let locationPoint = try await locationRecorder.requestCurrentPoint(
                journeyId: journey.id,
                segmentId: journey.webSegmentId
            )
            let visitPoint = VisitPointRecord(
                id: UUID(),
                journeyId: journey.id,
                segmentId: journey.webSegmentId,
                timestamp: locationPoint.timestamp,
                latitude: locationPoint.latitude,
                longitude: locationPoint.longitude,
                altitudeMeters: locationPoint.altitudeMeters,
                horizontalAccuracyMeters: locationPoint.horizontalAccuracyMeters,
                title: "GPS打卡",
                note: "使用目前 iPhone GPS 新增",
                source: "quickGps",
                sourceId: nil
            )
            try await repository.saveVisitPoint(visitPoint)
            let points = try await repository.visitPoints(journeyId: journey.id)
            activeVisitPointCount = points.count
            visitPointStatus = "Added current GPS visit point"
            enqueueVisitPointsStatus("visitPoint.added", journey: journey, points: [visitPoint])
            enqueueVisitPointsStatus("visitPoints.sync", journey: journey, points: points)
            await refreshDiagnostics()
        } catch {
            visitPointStatus = "Unable to add GPS visit: \(error.localizedDescription)"
            diagnostics.append(.error(visitPointStatus))
        }
    }

    func importPhotoGPSVisitPoints() async {
        let authorization = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        if authorization == .notDetermined {
            await requestPhotoPermission()
        }

        do {
            guard let journey = try await targetJourneyForVisitPoint() else {
                visitPointStatus = "No journey available for photo visits"
                return
            }
            let existing = try await repository.visitPoints(journeyId: journey.id)
            let existingPhotoIds = Set(existing.compactMap { point in
                point.source == "photoGps" ? point.sourceId : nil
            })
            let imported = photoImporter.visitPoints(
                for: journey,
                existingSourceIds: existingPhotoIds
            )
            for point in imported {
                try await repository.saveVisitPoint(point)
            }
            let points = try await repository.visitPoints(journeyId: journey.id)
            activeVisitPointCount = points.count
            visitPointStatus = imported.isEmpty
                ? "No new photo GPS visit points"
                : "Imported \(imported.count) photo GPS visit points"
            if !imported.isEmpty {
                enqueueVisitPointsStatus("visitPoints.sync", journey: journey, points: points)
            }
            await refreshDiagnostics()
        } catch {
            visitPointStatus = "Unable to import photo GPS: \(error.localizedDescription)"
            diagnostics.append(.error(visitPointStatus))
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
                let visitCount = try await repository.visitPointCount(journeyId: latest.id)
                activeLocationPointCount = pointCount
                activeVisitPointCount = visitCount
                latestJourneySummary = "\(latest.status.rawValue) | \(pointCount) GPS points | \(visitCount) visits | \(latest.id.uuidString.prefix(8))"
            } else {
                activeLocationPointCount = 0
                activeVisitPointCount = 0
                latestJourneySummary = "No stored journey"
            }
            diagnostics = [
                .info(locationPermissionStatus),
                .info(photoPermissionStatus),
                .info(notificationPermissionStatus),
                .info(replayEngineStatus),
                .info(offlinePackUpdateStatus),
                .info("Flight plan: \(recordingPlanStatus)"),
                .info("Visit points: \(visitPointStatus)"),
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

    func checkForOfflinePackUpdates(force: Bool = false) async {
        let now = Date()
        if
            !force,
            let lastOfflinePackUpdateCheck,
            now.timeIntervalSince(lastOfflinePackUpdateCheck) < 6 * 60 * 60
        {
            return
        }
        lastOfflinePackUpdateCheck = now
        offlinePackUpdateStatus = "Offline data: checking GitHub Pages"
        do {
            let result = try await offlinePackDownloadService.updateIfNeeded(force: force)
            switch result.status {
            case .alreadyCurrent:
                offlinePackUpdateStatus = "Offline data: current"
                await refreshDiagnostics()
            case .updated:
                offlinePackUpdateStatus = "Offline data: updated \(Self.formatBytes(result.downloadedBytes))"
                await refreshDiagnostics()
                replayEngineStatus = "Replay Engine: updated data ready; reopen Replay"
            }
        } catch {
            offlinePackUpdateStatus = "Offline data: update failed \(error.localizedDescription)"
            diagnostics.append(.error(offlinePackUpdateStatus))
        }
    }

    func selectFlightPlan(_ selectionKey: String) {
        guard let plan = flightPlans.first(where: { $0.selectionKey == selectionKey }) else {
            return
        }
        selectedFlightPlanKey = plan.selectionKey
        pendingFlightPlan = plan
        recordingPlanStatus = "Selected \(plan.flightNumber) \(plan.originIata) -> \(plan.destinationIata)"
        Self.saveSelectedFlightPlanKey(plan.selectionKey)
        enqueueBridgeMessage(type: "flightPlan.selected", payload: FlightPlanStatusPayload(plan: plan, status: "selected"))
    }

    func loadLatestJourneyInReplay() async {
        do {
            guard let journey = try await repository.recentJourneys(limit: 1).first else {
                replayEngineStatus = "Replay Engine: no stored journey"
                return
            }
            let points = try await repository.locationPoints(journeyId: journey.id, since: nil)
            let visitPoints = try await repository.visitPoints(journeyId: journey.id)
            activeJourney = journey
            activeLocationPointCount = points.count
            activeVisitPointCount = visitPoints.count
            enqueueRecordingStatus("recording.completed", journey: journey, points: points)
            enqueueVisitPointsStatus("visitPoints.sync", journey: journey, points: visitPoints)
            replayEngineStatus = "Replay Engine: queued latest stored journey"
        } catch {
            replayEngineStatus = "Replay Engine: load latest error \(error.localizedDescription)"
            diagnostics.append(.error(replayEngineStatus))
        }
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
        case "notification.schedule":
            scheduleNotificationMessage(message)
        case "file.export":
            exportFileMessage(message)
        case "recording.loadLatest":
            Task { await loadLatestJourneyInReplay() }
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
        upsertFlightPlan(plan)
        pendingFlightPlan = plan
        selectedFlightPlanKey = plan.selectionKey
        recordingPlanStatus = "Ready \(plan.flightNumber) \(plan.originIata) -> \(plan.destinationIata)"
        Self.saveSelectedFlightPlanKey(plan.selectionKey)
        enqueueBridgeMessage(type: "flightPlan.ready", payload: FlightPlanStatusPayload(plan: plan, status: "ready"))
        enqueueBridgeMessage(type: "flightPlan.selected", payload: FlightPlanStatusPayload(plan: plan, status: "selected"))
    }

    private func scheduleNotificationMessage(_ message: NativeBridgeMessage) {
        guard
            let data = message.payload.data(using: .utf8),
            let notification = try? JSONDecoder().decode(NotificationSchedulePayload.self, from: data)
        else {
            diagnostics.append(.error("Unable to decode notification request from Replay Engine"))
            return
        }
        notificationService.schedule(
            title: notification.title,
            body: notification.body,
            identifier: notification.identifier
        )
    }

    private func exportFileMessage(_ message: NativeBridgeMessage) {
        guard
            let data = message.payload.data(using: .utf8),
            let payload = try? JSONDecoder().decode(FileExportPayload.self, from: data),
            let fileData = Data(base64Encoded: payload.base64)
        else {
            diagnostics.append(.error("Unable to decode export file from Replay Engine"))
            return
        }

        do {
            let url = try saveExportFile(data: fileData, filename: payload.filename)
            diagnostics.append(.info("Export ready: \(url.lastPathComponent)"))
            presentExportShareSheet(url: url)
        } catch {
            diagnostics.append(.error("Unable to save export: \(error.localizedDescription)"))
        }
    }

    private func saveExportFile(data: Data, filename: String) throws -> URL {
        let rawName = URL(fileURLWithPath: filename).lastPathComponent
        let safeName = rawName.isEmpty ? "travel-globe-export.dat" : rawName.replacingOccurrences(of: ":", with: "-")
        let documents = try FileManager.default.url(
            for: .documentDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let exports = documents.appendingPathComponent("Exports", isDirectory: true)
        try FileManager.default.createDirectory(at: exports, withIntermediateDirectories: true)
        let url = exports.appendingPathComponent(safeName, isDirectory: false)
        try data.write(to: url, options: [.atomic])
        return url
    }

    private func presentExportShareSheet(url: URL) {
        let activity = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        guard
            let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first(where: { $0.activationState == .foregroundActive }),
            let root = scene.windows.first(where: { $0.isKeyWindow })?.rootViewController
        else {
            diagnostics.append(.info("Export saved to Documents/Exports: \(url.lastPathComponent)"))
            return
        }

        var presenter = root
        while let presented = presenter.presentedViewController {
            presenter = presented
        }
        if let popover = activity.popoverPresentationController {
            popover.sourceView = presenter.view
            popover.sourceRect = CGRect(x: presenter.view.bounds.midX, y: presenter.view.bounds.midY, width: 1, height: 1)
            popover.permittedArrowDirections = []
        }
        presenter.present(activity, animated: true)
    }

    private var selectedFlightPlan: FlightPlanRecord? {
        flightPlans.first(where: { $0.selectionKey == selectedFlightPlanKey }) ?? pendingFlightPlan
    }

    private func targetJourneyForVisitPoint() async throws -> JourneyRecord? {
        if let activeJourney {
            return activeJourney
        }
        let journeys = try await repository.recentJourneys(limit: 1)
        let latest = journeys.first
        activeJourney = latest
        return latest
    }

    private func upsertFlightPlan(_ plan: FlightPlanRecord) {
        var updated = flightPlans.filter { $0.selectionKey != plan.selectionKey }
        updated.insert(plan, at: 0)
        flightPlans = Array(updated.prefix(20))
        Self.saveStoredFlightPlans(flightPlans)
    }

    private func enqueueRecordingStatus(_ type: String, journey: JourneyRecord, points: [LocationPointRecord]?) {
        enqueueBridgeMessage(
            type: type,
            payload: RecordingStatusPayload(journey: journey, points: points)
        )
    }

    private func enqueueVisitPointsStatus(_ type: String, journey: JourneyRecord, points: [VisitPointRecord]) {
        enqueueBridgeMessage(
            type: type,
            payload: VisitPointsStatusPayload(journey: journey, points: points)
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
        OfflinePackDownloadService.replayEngineIndexURL()
            ?? Bundle.main.url(forResource: "index", withExtension: "html")
    }

    private static func formatBytes(_ bytes: Int) -> String {
        if bytes < 1_000 {
            return "\(bytes) B"
        }
        if bytes < 1_000_000 {
            return String(format: "%.1f KB", Double(bytes) / 1_000)
        }
        return String(format: "%.1f MB", Double(bytes) / 1_000_000)
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

    private static let flightPlansDefaultsKey = "travelGlobe.flightPlans"
    private static let selectedFlightPlanDefaultsKey = "travelGlobe.selectedFlightPlanKey"

    private static func loadStoredFlightPlans() -> [FlightPlanRecord] {
        guard
            let data = UserDefaults.standard.data(forKey: flightPlansDefaultsKey),
            let plans = try? JSONDecoder().decode([FlightPlanRecord].self, from: data)
        else {
            return []
        }
        return plans
    }

    private static func saveStoredFlightPlans(_ plans: [FlightPlanRecord]) {
        guard let data = try? JSONEncoder().encode(plans) else {
            return
        }
        UserDefaults.standard.set(data, forKey: flightPlansDefaultsKey)
    }

    private static func loadSelectedFlightPlanKey() -> String {
        UserDefaults.standard.string(forKey: selectedFlightPlanDefaultsKey) ?? ""
    }

    private static func saveSelectedFlightPlanKey(_ key: String) {
        UserDefaults.standard.set(key, forKey: selectedFlightPlanDefaultsKey)
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
    var departureTime: String?
    var durationMinutes: Int?
    var plannedRoute: [FlightPlanPointRecord]

    init(plan: FlightPlanRecord, status: String) {
        webJourneyId = plan.webJourneyId
        segmentId = plan.segmentId
        flightNumber = plan.flightNumber
        originIata = plan.originIata
        destinationIata = plan.destinationIata
        aircraftType = plan.aircraftType
        departureTime = plan.departureTime
        durationMinutes = plan.durationMinutes
        plannedRoute = plan.plannedRoute
        self.status = status
    }
}

private struct NotificationSchedulePayload: Decodable {
    var identifier: String
    var title: String
    var body: String
}

private struct FileExportPayload: Decodable {
    var filename: String
    var mimeType: String
    var base64: String
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

private struct VisitPointsStatusPayload: Encodable {
    var nativeJourneyId: String
    var webJourneyId: String?
    var segmentId: String?
    var status: String
    var points: [VisitPointPayload]

    init(journey: JourneyRecord, points: [VisitPointRecord]) {
        nativeJourneyId = journey.id.uuidString
        webJourneyId = journey.webJourneyId
        segmentId = journey.webSegmentId
        status = journey.status.rawValue
        self.points = points.map(VisitPointPayload.init(point:))
    }
}

private struct VisitPointPayload: Encodable {
    var id: String
    var timestamp: String
    var latitude: Double
    var longitude: Double
    var altitudeMeters: Double?
    var horizontalAccuracyMeters: Double?
    var title: String
    var note: String?
    var source: String
    var sourceId: String?

    init(point: VisitPointRecord) {
        id = point.id.uuidString
        timestamp = LiveLocationPayload.timestampFormatter.string(from: point.timestamp)
        latitude = point.latitude
        longitude = point.longitude
        altitudeMeters = point.altitudeMeters
        horizontalAccuracyMeters = point.horizontalAccuracyMeters
        title = point.title
        note = point.note
        source = point.source
        sourceId = point.sourceId
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
