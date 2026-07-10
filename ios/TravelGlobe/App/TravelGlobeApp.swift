import SwiftUI

@main
struct TravelGlobeApp: App {
    @StateObject private var appModel = TravelGlobeAppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(appModel)
        }
    }
}
