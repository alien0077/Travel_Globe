import SwiftUI
import WebKit

struct ReplayEngineView: UIViewRepresentable {
    @EnvironmentObject private var appModel: TravelGlobeAppModel

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.isOpaque = false
        webView.backgroundColor = .black
        webView.scrollView.backgroundColor = .black
        appModel.bridge.configure(webView)

        if let url = TravelGlobeAppModel.replayEngineIndexURL() {
            let readAccessURL = Bundle.main.resourceURL ?? url.deletingLastPathComponent()
            webView.loadFileURL(url, allowingReadAccessTo: readAccessURL)
        } else {
            webView.loadHTMLString("""
            <!doctype html>
            <html>
              <body style="margin:0;background:#030914;color:white;font:16px -apple-system;padding:24px;">
                <h1>Replay Engine not found</h1>
                <p>The app bundle is missing index.html.</p>
              </body>
            </html>
            """, baseURL: nil)
        }
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {}
}
