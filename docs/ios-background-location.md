# iOS Background Location

The iOS source tree includes the app shell and the service boundaries needed for background recording.

Implemented workspace pieces:

- SwiftUI root view and embedded WKWebView replay surface
- CoreLocation-facing recorder with walking, driving, flight, and significant-change profiles
- SQLite schema migration for journeys and route points
- bridge message handler for replay imports, exports, recording commands, and app status
- notification, PhotoKit import, offline pack download, and journey export services
- XcodeGen project and smoke test target

Real-device verification must confirm current Apple CoreLocation behavior for:

- When In Use and Always authorization
- reduced-accuracy authorization
- background location capability
- `allowsBackgroundLocationUpdates`
- low-power mode
- termination and restart recovery limits

The WebView must never be the canonical recorder.

The app, test bundle, and simulator test suite compile and pass with Xcode. Physical-device testing is still required for background delivery timing, reduced accuracy behavior, low-power behavior, and termination recovery.
