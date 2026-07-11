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
node scripts/prepare-geo-data.mjs
scripts/copy-replay-to-ios.sh
scripts/deploy-web-static.sh
scripts/serve-web-static.sh
./deploy.sh
/Users/alien/Desktop/xcodegen/bin/xcodegen generate
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild build -quiet -scheme TravelGlobe -destination 'generic/platform=iOS Simulator' -derivedDataPath /private/tmp/TravelGlobeDerived CODE_SIGNING_ALLOWED=NO
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild build-for-testing -quiet -scheme TravelGlobe -destination 'generic/platform=iOS Simulator' -derivedDataPath /private/tmp/TravelGlobeDerived CODE_SIGNING_ALLOWED=NO
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild test -quiet -scheme TravelGlobe -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.2' -derivedDataPath /private/tmp/TravelGlobeDerived CODE_SIGNING_ALLOWED=NO
```

The production build uses relative asset paths so `replay-engine/dist` can be served from static hosting or opened by an offline-capable local server.

## Deployment

- iOS app: `./deploy.sh` mirrors the TWStockTracker deployment flow with XcodeGen, automatic signing, physical-device build, `xctrace` device detection, and `ios-deploy` launch.
- Web static hosting: Netlify is deployed at `https://travel-globe-alien0077.netlify.app` and is connected to GitHub CI/CD. `.github/workflows/web-static.yml` remains available for GitHub Pages if needed.
- Field testing: use `docs/field-test.md` for the short route, permission, and long background recording checks.
- App Store: not in scope for this project phase. Use local physical-device deployment and web static hosting.
- Custom domain: optional. The Netlify subdomain is production-ready; add a custom domain only when a branded URL is needed.

## Verification Boundary

The browser replay layer is verified with typecheck, unit tests, static build, and Playwright desktop/mobile checks. The iOS app builds and its simulator tests pass with Xcode. Real CoreLocation background behavior, PhotoKit permissions, notification delivery, production offline geographic datasets, and long-running recording recovery still require physical-device and data-license verification.
