import SwiftUI
import WebKit

struct ReplayEngineView: UIViewRepresentable {
    @EnvironmentObject private var appModel: TravelGlobeAppModel

    func makeCoordinator() -> Coordinator {
        Coordinator(appModel: appModel)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        if let assetBaseURL = TravelGlobeAppModel.replayEngineIndexURL()?.deletingLastPathComponent().absoluteString {
            let assetBaseLiteral = Self.javascriptStringLiteral(assetBaseURL)
            configuration.userContentController.addUserScript(WKUserScript(
                source: "window.__TRAVEL_GLOBE_ASSET_BASE__ = \(assetBaseLiteral);",
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            ))
        }
        configuration.userContentController.addUserScript(Self.diagnosticsScript)
        configuration.userContentController.add(context.coordinator, name: "replayDiagnostics")

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.isOpaque = false
        webView.backgroundColor = .black
        webView.scrollView.backgroundColor = .black
        webView.scrollView.isScrollEnabled = false
        webView.scrollView.bounces = false
        webView.scrollView.alwaysBounceVertical = false
        webView.scrollView.alwaysBounceHorizontal = false
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
            var detail = event.error && event.error.stack ? event.error.stack : event.message;
            if (event.filename || event.lineno || event.colno) {
              detail += ' @ ' + (event.filename || 'inline') + ':' + (event.lineno || 0) + ':' + (event.colno || 0);
            }
            send('JS error: ' + detail);
          });
          window.addEventListener('unhandledrejection', function (event) {
            send('Promise rejection: ' + (event.reason && event.reason.message ? event.reason.message : event.reason));
          });
        })();
        """,
        injectionTime: .atDocumentStart,
        forMainFrameOnly: true
    )

    static func javascriptStringLiteral(_ value: String) -> String {
        guard
            let data = try? JSONEncoder().encode(value),
            let literal = String(data: data, encoding: .utf8)
        else {
            return "\"\""
        }
        return literal
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        private let appModel: TravelGlobeAppModel
        private var hasRuntimeDiagnostic = false
        private var didInjectReplayBundle = false

        init(appModel: TravelGlobeAppModel) {
            self.appModel = appModel
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self, weak webView] in
                guard let self, let webView else { return }
                webView.evaluateJavaScript("Boolean(document.querySelector('.app-shell'))") { [weak self] result, _ in
                    guard let self else { return }
                    if (result as? Bool) == true {
                        Task { @MainActor in
                            self.appModel.updateReplayEngineStatus("loaded")
                        }
                        return
                    }
                    self.injectReplayBundle(into: webView)
                }
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
            if hasRuntimeDiagnostic && body == "JS error: Script error." {
                return
            }
            hasRuntimeDiagnostic = true
            Task { @MainActor in
                appModel.updateReplayEngineStatus(body)
            }
        }

        private func report(_ error: Error) {
            Task { @MainActor in
                appModel.updateReplayEngineStatus("load error \(error.localizedDescription)")
            }
        }

        private func injectReplayBundle(into webView: WKWebView) {
            guard !didInjectReplayBundle else { return }
            didInjectReplayBundle = true

            guard let scriptURL = Bundle.main.url(
                forResource: "index",
                withExtension: "js",
                subdirectory: "ReplayEngine"
            ) else {
                Task { @MainActor in
                    appModel.updateReplayEngineStatus("missing index.js")
                }
                return
            }

            do {
                let source = try String(contentsOf: scriptURL, encoding: .utf8)
                let assetBase = scriptURL.deletingLastPathComponent().absoluteString
                let assetBaseLiteral = ReplayEngineView.javascriptStringLiteral(assetBase)
                let bootstrappedSource = "window.__TRAVEL_GLOBE_ASSET_BASE__ = \(assetBaseLiteral);\n" + source
                Task { @MainActor in
                    appModel.updateReplayEngineStatus("injecting")
                }
                webView.evaluateJavaScript(bootstrappedSource) { [weak self] _, error in
                    guard let self else { return }
                    if let error {
                        Task { @MainActor in
                            self.appModel.updateReplayEngineStatus("inject error \(error.localizedDescription)")
                        }
                    } else if !self.hasRuntimeDiagnostic {
                        Task { @MainActor in
                            self.appModel.updateReplayEngineStatus("injected")
                        }
                    }
                }
            } catch {
                Task { @MainActor in
                    appModel.updateReplayEngineStatus("script read error \(error.localizedDescription)")
                }
            }
        }
    }
}
