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

The app and test bundle compile with Xcode. A full simulator `xcodebuild test` run previously reached simulator materialization and was interrupted after hanging; use `build-for-testing` as the reliable CI gate until the simulator runtime issue is cleared.
