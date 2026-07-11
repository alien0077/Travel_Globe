import SwiftUI
import WebKit

struct ReplayEngineView: UIViewRepresentable {
    @EnvironmentObject private var appModel: TravelGlobeAppModel

    func makeCoordinator() -> Coordinator {
        Coordinator(appModel: appModel)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.addUserScript(Self.diagnosticsScript)
        configuration.userContentController.add(context.coordinator, name: "replayDiagnostics")

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.isOpaque = false
        webView.backgroundColor = .black
        webView.scrollView.backgroundColor = .black
        webView.navigationDelegate = context.coordinator
        appModel.bridge.configure(webView)

        if let url = TravelGlobeAppModel.replayEngineIndexURL() {
            let readAccessURL = Bundle.main.resourceURL ?? url.deletingLastPathComponent()
            appModel.updateReplayEngineStatus("loading index.html")
            webView.loadFileURL(url, allowingReadAccessTo: readAccessURL)
        } else {
            appModel.updateReplayEngineStatus("missing index.html")
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

    static let diagnosticsScript = WKUserScript(
        source: """
        (function () {
          function send(message) {
            try {
              window.webkit.messageHandlers.replayDiagnostics.postMessage(String(message));
            } catch (_) {}
          }
          window.addEventListener('error', function (event) {
            send('JS error: ' + event.message);
          });
          window.addEventListener('unhandledrejection', function (event) {
            send('Promise rejection: ' + (event.reason && event.reason.message ? event.reason.message : event.reason));
          });
        })();
        """,
        injectionTime: .atDocumentStart,
        forMainFrameOnly: true
    )

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        private let appModel: TravelGlobeAppModel

        init(appModel: TravelGlobeAppModel) {
            self.appModel = appModel
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            Task { @MainActor in
                appModel.updateReplayEngineStatus("loaded")
            }
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            report(error)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            report(error)
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let body = message.body as? String else { return }
            Task { @MainActor in
                appModel.updateReplayEngineStatus(body)
            }
        }

        private func report(_ error: Error) {
            Task { @MainActor in
                appModel.updateReplayEngineStatus("load error \(error.localizedDescription)")
            }
        }
    }
}
