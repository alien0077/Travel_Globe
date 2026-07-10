import Foundation

@MainActor
final class TravelGlobeAppModel: ObservableObject {
    @Published var activeJourney: JourneyRecord?
    @Published var recordingState: RecordingState = .idle
    @Published var diagnostics: [RecordingDiagnostic] = []

    let locationRecorder: LocationRecorder
    let bridge = TravelGlobeBridge()
    let repository: JourneyRepository
    let exporter = JourneyExportService()

    init(
        repository: JourneyRepository = SQLiteJourneyRepository(database: TravelGlobeDatabase())
    ) {
        self.repository = repository
        self.locationRecorder = LocationRecorder(repository: repository)
    }

    func startFlightRecording() async {
        do {
            let journey = try await repository.createJourney(title: "New Flight Recording", segmentType: .flight)
            activeJourney = journey
            recordingState = .recording
            try await locationRecorder.start(journeyId: journey.id, profile: .flight)
        } catch {
            diagnostics.append(.error("Unable to start recording: \(error.localizedDescription)"))
        }
    }

    func stopRecording() async {
        await locationRecorder.stop()
        recordingState = .completed
    }
}
