import SwiftUI

struct RootView: View {
    @EnvironmentObject private var appModel: TravelGlobeAppModel

    var body: some View {
        NavigationStack {
            List {
                Section("Recorder") {
                    Text("State: \(appModel.recordingState.rawValue)")
                    Text("GPS points: \(appModel.activeLocationPointCount)")
                    Text(appModel.latestJourneySummary)
                    Button("Start Flight Recording") {
                        Task { await appModel.startFlightRecording() }
                    }
                    Button("Stop Recording") {
                        Task { await appModel.stopRecording() }
                    }
                }

                Section("Replay") {
                    NavigationLink("Open Replay Engine") {
                        ReplayEngineView()
                    }
                    Text(appModel.replayEngineStatus)
                }

                Section("Diagnostics") {
                    Button("Refresh Diagnostics") {
                        Task { await appModel.refreshDiagnostics() }
                    }
                    Button("Request Photo Access") {
                        Task { await appModel.requestPhotoPermission() }
                    }
                    Button("Request Notifications") {
                        Task { await appModel.requestNotificationPermission() }
                    }
                    ForEach(appModel.diagnostics) { diagnostic in
                        Text(diagnostic.message)
                    }
                }
            }
            .navigationTitle("Travel Globe")
        }
    }
}
