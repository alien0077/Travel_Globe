import SwiftUI

struct RootView: View {
    @EnvironmentObject private var appModel: TravelGlobeAppModel
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header
                    flightCard
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
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            Task { await appModel.checkForOfflinePackUpdates() }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Flight")
                .font(.title2.weight(.bold))
                .foregroundStyle(.white)
            Text("Live GPS 或使用目前航線進行模擬")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding(.top, 4)
    }

    private var flightCard: some View {
        DashboardCard(title: "Flight") {
            VStack(alignment: .leading, spacing: 14) {
                Picker(
                    "模式",
                    selection: Binding(
                        get: { appModel.flightMode },
                        set: { appModel.selectFlightMode($0) }
                    )
                ) {
                    Text("Live GPS").tag(FlightMode.live)
                    Text("模擬航線").tag(FlightMode.simulation)
                }
                .pickerStyle(.segmented)

                StatusPill(text: appModel.flightStatus)
                StatusPill(text: appModel.recordingPlanStatus)

                if !appModel.flightPlans.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("模擬航線 / Flight plan")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(.secondary)
                        Picker(
                            "Flight plan",
                            selection: Binding(
                                get: { appModel.selectedFlightPlanKey },
                                set: { appModel.selectFlightPlan($0) }
                            )
                        ) {
                            ForEach(appModel.flightPlans) { plan in
                                Text(plan.displayTitle)
                                    .tag(plan.selectionKey)
                            }
                        }
                        .pickerStyle(.menu)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                HStack(spacing: 10) {
                    ActionButton(title: "開始 Live") {
                        Task { await appModel.startLiveFlight() }
                    }
                    ActionButton(title: "停止 Live", style: .secondary) {
                        Task { await appModel.stopLiveFlight() }
                    }
                }

                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                    ActionButton(title: "GPS打卡", style: .secondary) {
                        Task { await appModel.addCurrentGPSVisitPoint() }
                    }
                    ActionButton(title: "照片打卡", style: .secondary) {
                        Task { await appModel.importPhotoGPSVisitPoints() }
                    }
                }

                FlightView()
                    .frame(height: 640)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
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
