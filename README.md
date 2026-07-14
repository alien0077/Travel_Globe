# Travel Globe

Every journey deserves a beautiful replay.

Travel Globe is a local-first travel recording and replay system. The current workspace includes an offline Replay Engine, portable journey contracts, product-mode service modules, and a SwiftUI iOS shell that embeds the static replay bundle.

## Current Scope

- Monorepo scaffold for contracts, shared fixtures, docs, scripts, and the Replay Engine.
- Versioned JSON Schema contracts for portable journey data.
- Vite + TypeScript + Three.js standalone Replay Engine prototype.
- Vitest coverage for geodesic distance, bearing, great-circle interpolation, and journey schema validation.
- Browser import for journey JSON and stored `.travelglobe` packages.
- Browser export for `.travelglobe` packages and share-safe redacted JSON.
- Timeline event navigation, timeline scrub, nearest-landmark guidance, and desktop/mobile preview verification.
- Product-mode modules for travel planning, journal export, time-machine replay summaries, route statistics, offline pack state, auto recording policy, photo matching, and travel notification rules.
- SwiftUI iOS app shell with CoreLocation-facing recorder service, SQLite schema setup, WKWebView bridge, PhotoKit import service, offline pack download service, notification service, and bundled Replay Engine resources.
- Figma UI/UX reference file for desktop replay and iPhone recording surfaces.

## Commands

```bash
npm --prefix replay-engine install
npm --prefix replay-engine run typecheck
npm --prefix replay-engine run test
npm --prefix replay-engine run build
npm --prefix replay-engine run preview
npm --prefix replay-engine run verify:preview
npm --prefix replay-engine run prepare:aircraft-models -- --dry-run
npm --prefix replay-engine run import:aircraft-model -- --aircraft a350-900 --file /path/to/a350-900.glb
node scripts/prepare-geo-data.mjs
scripts/copy-replay-to-ios.sh
scripts/deploy-web-static.sh
scripts/serve-web-static.sh
./deploy.sh
./deploy.sh ios-device
/Users/alien/Desktop/xcodegen/bin/xcodegen generate
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild build -quiet -scheme TravelGlobe -destination 'generic/platform=iOS Simulator' -derivedDataPath /private/tmp/TravelGlobeDerived CODE_SIGNING_ALLOWED=NO
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild build-for-testing -quiet -scheme TravelGlobe -destination 'generic/platform=iOS Simulator' -derivedDataPath /private/tmp/TravelGlobeDerived CODE_SIGNING_ALLOWED=NO
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild test -quiet -scheme TravelGlobe -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.2' -derivedDataPath /private/tmp/TravelGlobeDerived CODE_SIGNING_ALLOWED=NO
```

The production build uses relative asset paths so `replay-engine/dist` can be served from static hosting or opened by an offline-capable local server.

## Data Coverage

- Airports: the preload airport picker uses the generated OurAirports scheduled-service index with IATA codes only. It is intended for commercial-flight airports, not every heliport, closed airport, or private strip.
- Aviation context: the core offline pack includes OurAirports frequencies and navaids for airport context and product stats.
- Places and labels: route labels/HUD nearby guidance use a merged set of curated East Asia/Southeast Asia landmarks plus Natural Earth 110m populated places. The global city layer currently contributes major/populated city names; richer global landmarks are not complete yet.
- Globe geography: Natural Earth 110m coastlines and country borders render on the globe.
- Route filtering: globe labels and HUD nearby places are filtered to landmarks/cities near the active route so an Alaska/Europe route does not pull unrelated East Asia labels.
- Flight numbers: the offline schedule seed currently resolves `CI100` (`TPE -> NRT`), `BR190` (`TPE -> HND`), `FD234` (`KHH -> NRT`), and `FD235` (`NRT -> KHH`). Wider airline schedule lookup still requires an imported/licensed schedule source or a flight API.
- Day/night rendering: the globe lighting now changes by replay time and local longitude, and route-nearby cities glow at night as simulated city lights. This is a procedural route-city effect, not a full NASA Black Marble night-lights texture.
- Live GPS to Travel Records: in the iOS app, apply one or more flight preloads in Replay Engine first, then choose the target plan from the native `Record Into` picker before pressing Start. Start binds the selected flight plan to native GPS recording through the shared `segmentId`; Stop marks the journey completed and sends the true GPS track back into Travel Records and Travel Atlas. Pressing Apply alone only creates a planned flight plan.
- Visit points: iOS journeys can add "GPS打卡" from a one-shot current GPS fix or "照片打卡" from PhotoKit `PHAsset.location` within the journey time range. Both are stored as `visit_points`, synced to Replay Engine as travel-record events, and do not mutate raw flight GPS tracks.
- Editable Travel Records: completed journeys support a metadata/edit overlay for adding manual events, editing record title/subtitle, hiding records, and correcting flight summary fields. Original SQLite GPS points remain read-only and are not changed by manual edits.
- Aircraft model attribution: bundled A320, A321, A350, A380, B737, B767, B777, and B787 GLB models are marked CC BY via Sketchfab in per-aircraft `license.json` files and are copied into the iOS app bundle with the Replay Engine assets.

## Deployment

- Web static hosting: `./deploy.sh` verifies the Replay Engine, pushes `main`, watches the GitHub Pages workflow, and checks `https://alien0077.github.io/Travel_Globe/`.
- iOS app: `./deploy.sh ios-device` mirrors the TWStockTracker deployment flow with XcodeGen, automatic signing, physical-device build, `xctrace` device detection, and `ios-deploy` or `devicectl` launch.
- Field testing: use `docs/field-test.md` for the short route, permission, and long background recording checks.
- App Store: not in scope for this project phase. Use local physical-device deployment and web static hosting.
- Custom domain: optional. Netlify is not the primary verification target while the `alien0077` Netlify team credits are exhausted; use GitHub Pages checks unless Netlify billing is explicitly being handled.

## Verification Boundary

The browser replay layer is verified with typecheck, unit tests, static build, and Playwright desktop/mobile checks. The iOS app is verified with a generic simulator build smoke; simulator tests require a concrete available simulator and may be blocked when CoreSimulatorService is unavailable. Real CoreLocation background behavior, PhotoKit permissions and photo-location availability, notification delivery, production offline geographic datasets, and long-running recording recovery still require physical-device and data-license verification.
