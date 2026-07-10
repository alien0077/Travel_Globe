import SwiftUI

struct RootView: View {
    @EnvironmentObject private var appModel: TravelGlobeAppModel

    var body: some View {
        NavigationStack {
            List {
                Section("Recorder") {
                    Text("State: \(appModel.recordingState.rawValue)")
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
                }

                Section("Diagnostics") {
                    ForEach(appModel.diagnostics) { diagnostic in
                        Text(diagnostic.message)
                    }
                }
            }
            .navigationTitle("Travel Globe")
        }
    }
}
