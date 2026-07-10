import Foundation
import WebKit

@MainActor
final class TravelGlobeBridge: NSObject, WKScriptMessageHandler, ObservableObject {
    @Published var receivedMessages: [NativeBridgeMessage] = []

    func configure(_ webView: WKWebView) {
        webView.configuration.userContentController.add(self, name: "travelGlobe")
    }

    func send(_ message: NativeBridgeMessage, to webView: WKWebView) {
        guard let data = try? JSONEncoder().encode(message),
              let json = String(data: data, encoding: .utf8)
        else { return }
        webView.evaluateJavaScript("window.TravelGlobeNative?.receive(\(json));")
    }

    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            let bridgeMessage = NativeBridgeMessage(
                version: "1.0",
                requestId: nil,
                type: "web.message",
                payload: "\(message.body)"
            )
            receivedMessages.append(bridgeMessage)
        }
    }
}

struct NativeBridgeMessage: Codable, Identifiable {
    var id = UUID()
    var version: String
    var requestId: String?
    var type: String
    var payload: String
}
