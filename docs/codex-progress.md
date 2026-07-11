# Codex Progress

## 2026-07-10

- Created Phase 0-1 monorepo scaffold.
- Added documentation skeleton for architecture, data model, privacy, offline data, iOS background location, and replay engine.
- Added versioned JSON Schema contracts and a realistic Taipei-to-Tokyo sample flight.
- Implemented the standalone Vite + TypeScript + Three.js Replay Engine prototype.
- Added unit tests for geodesic distance, bearing, great-circle interpolation, and schema validation.
- Added stored `.travelglobe` package export/import support.
- Added share-safe JSON export with endpoint coordinate redaction.
- Added timeline event navigation, local browser persistence, and nearest-landmark / window-side guidance.
- Added Playwright preview verification for desktop and mobile WebGL rendering.
- Created the Figma UI/UX reference file: https://www.figma.com/design/xeQEwHGHGe4WtArLk7OIpY
- Added product-mode services for travel planning, journal markdown, time-machine summaries, route statistics, offline packs, photo matching, auto recording, and notifications.
- Added Replay Engine product panel controls for journal export and offline pack installation.
- Added responsive desktop/mobile product-panel styling and expanded Playwright verification to cover the product modes.
- Added SwiftUI iOS shell with CoreLocation-facing recorder, SQLite schema setup, WKWebView bridge, PhotoKit import service, offline pack download service, notification service, and Replay Engine resource bundle.
- Added XcodeGen project generation and iOS smoke test target.
- Verified `npm --prefix replay-engine run typecheck`.
- Verified `npm --prefix replay-engine run test`.
- Verified `npm --prefix replay-engine run build`.
- Verified `npm --prefix replay-engine run verify:preview`.
- Verified `scripts/copy-replay-to-ios.sh`.
- Verified `/Users/alien/Desktop/xcodegen/bin/xcodegen generate`.
- Verified iOS `xcodebuild build` for generic iOS Simulator.
- Verified iOS `xcodebuild build-for-testing` for generic iOS Simulator.
- Verified full iOS `xcodebuild test` on iPhone 15 simulator, including SQLite persistence coverage.
- Replaced the remaining in-memory iOS journey repository behavior with SQLite inserts, ordered point queries, and completion updates.
- Added deterministic offline geo pack manifest generation from local fixture landmarks.
- Switched Replay Engine build output to stable asset names for safer iOS resource embedding.
- Adopted the TWStockTracker iOS signing/deploy pattern for Travel Globe with automatic signing and physical-device deployment script.
- Added GitHub Pages static hosting workflow and local static web deployment helpers.
- Documented production data-source choices for Natural Earth, NASA, OurAirports, and isolated OSM packs.
- Verified physical-device build, install, and launch on `Alien iPhone 14` using `devicectl` with bundle id `com.alienchang.TravelGlobe`.
- Updated iOS resource packaging so the embedded Replay Engine is preserved as a `ReplayEngine` folder inside the app bundle.
- Connected Netlify CI/CD to GitHub `alien0077/Travel_Globe` so future pushes and pull requests can trigger Netlify builds.
- Added `docs/field-test.md` for route recording, permission, and long-background real-device validation.
- Downloaded the first production source-data baseline from Natural Earth, OurAirports, and NASA Visible Earth.
- Confirmed App Store/TestFlight work is out of scope for the current phase and custom domain usage is optional.
