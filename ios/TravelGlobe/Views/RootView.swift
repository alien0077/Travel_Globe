import SwiftUI

struct RootView: View {
    @EnvironmentObject private var appModel: TravelGlobeAppModel

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header
                    recorderCard
                    replayCard
                    diagnosticsCard
                }
                .padding(.horizontal, 20)
                .padding(.top, 14)
                .padding(.bottom, 28)
            }
            .background(Color.black.ignoresSafeArea())
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text("Travel Globe")
                        .font(.headline.weight(.semibold))
                        .foregroundStyle(.white)
                }
            }
        }
        .tint(.cyan)
        .dynamicTypeSize(.small ... .xLarge)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Flight Recorder")
                .font(.title2.weight(.bold))
                .foregroundStyle(.white)
            Text("Record, inspect, and replay offline journeys.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding(.top, 4)
    }

    private var recorderCard: some View {
        DashboardCard(title: "Recorder") {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .top, spacing: 12) {
                    MetricBlock(title: "State", value: appModel.recordingState.rawValue.capitalized)
                    MetricBlock(title: "GPS", value: "\(appModel.activeLocationPointCount) points")
                }

                Text(appModel.latestJourneySummary)
                    .font(.footnote.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .minimumScaleFactor(0.82)

                HStack(spacing: 10) {
                    ActionButton(title: "Start") {
                        Task { await appModel.startFlightRecording() }
                    }
                    ActionButton(title: "Stop", style: .secondary) {
                        Task { await appModel.stopRecording() }
                    }
                }
            }
        }
    }

    private var replayCard: some View {
        DashboardCard(title: "Replay") {
            VStack(alignment: .leading, spacing: 12) {
                NavigationLink {
                    ReplayEngineView()
                        .ignoresSafeArea(.container, edges: .bottom)
                        .navigationTitle("Replay")
                        .navigationBarTitleDisplayMode(.inline)
                } label: {
                    HStack {
                        Text("Open Replay Engine")
                            .font(.headline)
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.subheadline.weight(.semibold))
                    }
                    .foregroundStyle(.white)
                    .padding(.vertical, 4)
                }

                StatusPill(text: appModel.replayEngineStatus)
            }
        }
    }

    private var diagnosticsCard: some View {
        DashboardCard(title: "Diagnostics") {
            VStack(alignment: .leading, spacing: 12) {
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                    ActionButton(title: "Refresh", style: .secondary) {
                        Task { await appModel.refreshDiagnostics() }
                    }
                    ActionButton(title: "Photos", style: .secondary) {
                        Task { await appModel.requestPhotoPermission() }
                    }
                    ActionButton(title: "Notifications", style: .secondary) {
                        Task { await appModel.requestNotificationPermission() }
                    }
                }

                VStack(alignment: .leading, spacing: 8) {
                    StatusRow(label: "Location", value: appModel.locationPermissionStatus.replacingOccurrences(of: "Location: ", with: ""))
                    StatusRow(label: "Photos", value: appModel.photoPermissionStatus.replacingOccurrences(of: "Photos: ", with: ""))
                    StatusRow(label: "Notifications", value: appModel.notificationPermissionStatus.replacingOccurrences(of: "Notifications: ", with: ""))
                    StatusRow(label: "Journeys", value: "\(appModel.storedJourneyCount)")
                }
            }
        }
    }
}

private struct DashboardCard<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title.uppercased())
                .font(.caption.weight(.bold))
                .foregroundStyle(.yellow)
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(red: 0.08, green: 0.11, blue: 0.15))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.white.opacity(0.08), lineWidth: 1)
        }
    }
}

private struct MetricBlock: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.headline.weight(.semibold))
                .foregroundStyle(.white)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct StatusRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(label)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .frame(width: 92, alignment: .leading)
            Text(value)
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.white)
                .lineLimit(2)
                .minimumScaleFactor(0.8)
            Spacer(minLength: 0)
        }
    }
}

private struct StatusPill: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.footnote.weight(.semibold))
            .foregroundStyle(.cyan)
            .lineLimit(2)
            .minimumScaleFactor(0.8)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(Color.cyan.opacity(0.12))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct ActionButton: View {
    enum Style {
        case primary
        case secondary
    }

    let title: String
    var style: Style = .primary
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .lineLimit(1)
                .minimumScaleFactor(0.75)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .padding(.horizontal, 10)
                .background(style == .primary ? Color.cyan : Color.white.opacity(0.08))
                .foregroundStyle(style == .primary ? Color.black : Color.white)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}
