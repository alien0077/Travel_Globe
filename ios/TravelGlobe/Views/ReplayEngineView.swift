import SwiftUI
import WebKit

struct ReplayEngineView: UIViewRepresentable {
    @EnvironmentObject private var appModel: TravelGlobeAppModel

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        appModel.bridge.configure(webView)

        if let url = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "ReplayEngine") {
            webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
        }
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {}
}
