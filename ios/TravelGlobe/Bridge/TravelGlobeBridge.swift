import Foundation
import WebKit

@MainActor
final class TravelGlobeBridge: NSObject, WKScriptMessageHandler, ObservableObject {
    @Published var receivedMessages: [NativeBridgeMessage] = []
    var onMessage: ((NativeBridgeMessage) -> Void)?

    func configure(_ webView: WKWebView) {
        let controller = webView.configuration.userContentController
        controller.addUserScript(WKUserScript(
            source: """
            window.TravelGlobeNative = window.TravelGlobeNative || {
              post: function(message) {
                window.webkit.messageHandlers.travelGlobe.postMessage(message);
              },
              receive: function(message) {
                window.dispatchEvent(new CustomEvent('travelglobe:native', { detail: message }));
              }
            };
            """,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        ))
        controller.add(self, name: "travelGlobe")
    }

    func send(_ message: NativeBridgeMessage, to webView: WKWebView) {
        guard let data = try? JSONEncoder().encode(message),
              let json = String(data: data, encoding: .utf8)
        else { return }
        webView.evaluateJavaScript("window.TravelGlobeNative?.receive(\(json));")
    }

    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            let bridgeMessage = Self.decodeBridgeMessage(message.body)
            receivedMessages.append(bridgeMessage)
            onMessage?(bridgeMessage)
        }
    }

    private static func decodeBridgeMessage(_ body: Any) -> NativeBridgeMessage {
        guard let dictionary = body as? [String: Any] else {
            return NativeBridgeMessage(
                version: "1.0",
                requestId: nil,
                type: "web.message",
                payload: stringifyPayload(body)
            )
        }
        let payload = dictionary["payload"] ?? body
        return NativeBridgeMessage(
            version: dictionary["version"] as? String ?? "1.0",
            requestId: dictionary["requestId"] as? String,
            type: dictionary["type"] as? String ?? "web.message",
            payload: stringifyPayload(payload)
        )
    }

    private static func stringifyPayload(_ body: Any) -> String {
        if let body = body as? String {
            return body
        }
        guard JSONSerialization.isValidJSONObject(body),
              let data = try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys]),
              let json = String(data: data, encoding: .utf8)
        else {
            return "\(body)"
        }
        return json
    }
}

struct NativeBridgeMessage: Codable, Identifiable {
    var id = UUID()
    var version: String
    var requestId: String?
    var type: String
    var payload: String
}
