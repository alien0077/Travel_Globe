# Travel Globe Handoff

Updated: 2026-07-14

## Current Direction

Travel Globe is moving from a pure replay globe toward a Travel Atlas experience:

- planned flight route before departure
- actual GPS track during flight
- travel records generated from flight events and future media/GPS context
- offline-first data packs with explicit source attribution

## Flight Data Plan

### OurAirports

Use OurAirports as the free airport master-data layer:

- airports.csv: global airport coordinates, IATA/ICAO, airport type, country/region, municipality
- runways.csv: runway count and longest runway metadata
- frequencies.csv: transformed into aviation context records for airport detail/product status
- countries.csv / regions.csv: readable country and admin-region labels
- navaids.csv: transformed into aviation context records, not used by route drawing yet

Attribution to show in About / Data Sources:

`Airport and runway data provided by OurAirports.`

Implemented files:

- `scripts/download-geo-data.sh`
- `scripts/prepare-airport-index.mjs`
- `shared/offline-packs/core-global/airports-index.json`
- `shared/offline-packs/core-global/aviation-context-index.json`
- `shared/offline-packs/core-global/ourairports-manifest.json`
- `replay-engine/src/flight-preload/airportIndex.ts`

### Flight Number Source

First version does not require a paid flight API. The app resolves known flight numbers from an offline schedule seed:

- `CI100`: China Airlines, `TPE -> NRT`, default duration 185 minutes
- `BR190`: EVA Air, `TPE -> HND`, default duration 190 minutes
- `FD234`: Thai AirAsia, Taiwan departure segment `KHH -> NRT`, default duration 235 minutes, aircraft seed `A320`
- `FD235`: Thai AirAsia, displayed as `NRT -> KHH` for the return segment, default duration 235 minutes, aircraft seed `A320`

Implemented file:

- `replay-engine/src/flight-preload/flightScheduleIndex.ts`

Behavior:

- If the user enters `CI100` only, the app resolves `TPE -> NRT`.
- If the user enters origin/destination IATA, those fields override the schedule seed.
- If the flight number is unknown and origin/destination are blank, the app asks for manual IATA input.

### Great Circle Planned Route

When no real filed route is available, Travel Globe uses Great Circle interpolation as the planned route. This is enough for the first Planned vs Actual experience:

- Planned: offline schedule plus OurAirports coordinates
- Actual: GPS points collected during flight or imported after the trip

Paid flight APIs remain deferred. They are only needed when the product requires real-time status, historical actual tracks, filed route strings, ATC waypoints, aircraft registration, or delay/cancel data.

## OurAirports Refresh Cadence

OurAirports CSVs update daily upstream. Travel Globe should refresh with review, not silently in app runtime:

- Weekly drift check: `.github/workflows/ourairports-data.yml` runs Monday 03:17 UTC.
- Manual refresh: trigger the workflow with `workflow_dispatch` before a release or when an airport/code correction matters.
- Reviewed monthly refresh: if the weekly check reports a diff, run the local refresh commands, inspect the generated index diff, then commit.

Local refresh:

```bash
scripts/download-geo-data.sh
npm --prefix replay-engine run prepare:airports
npm --prefix replay-engine run typecheck
npm --prefix replay-engine run test
npm --prefix replay-engine run build
```

## Implemented This Pass

- Travel Atlas UI with travel record timeline and region filters.
- Flight preload panel in Replay Engine.
- Offline `CI100 -> TPE -> NRT` schedule resolution.
- OurAirports-generated global airport index.
- OurAirports-generated frequency and navaid aviation context index.
- Natural Earth coastline/country boundary extraction and globe rendering.
- Natural Earth 110m populated places merged into route-filtered labels/HUD context.
- Procedural replay-time day/night lighting and route-nearby city light points for night segments.
- Offline pack manifests wired to generated Natural Earth and OurAirports indexes.
- Runtime adapter browser export path for `.travelglobe` and share-safe JSON.
- Great Circle planned route generation with replay, processed, and raw routes.
- Preview verification for `CI100` preload without manually entering origin/destination.
- GitHub Actions drift check for OurAirports source/index changes.
- GitHub Actions iOS workflow now creates a named simulator before resolving the test destination.

## Still Partial

These are the main half-finished areas to continue next:

- Network flight-plan provider: source type exists, but no API implementation or key-management path is wired.
- Flight schedule coverage: only a seed schedule index exists; broad flight-number lookup needs an imported or licensed schedule source.
- Flight schedule accuracy: FD234/FD235 currently know route segment, rough duration, and aircraft family only; exact seasonal schedule, operating days, departure/arrival time, aircraft substitutions, and multi-leg `DMK-KHH-NRT` / `NRT-KHH-DMK` modeling still need an API or reviewed timetable import.
- Frequencies and navaids: transformed into an aviation context index and visible in product stats; a full airport detail/search UI is still not built.
- Offline packs: core pack state now references real generated layers; install/download remains a browser-local product state, not a real remote package installer.
- Geographic borders: Natural Earth 110m coastlines/country boundaries now render on the globe; higher-detail packs and label ranking remain future work.
- Landmark/place coverage: current labels merge curated East Asia/Southeast Asia landmarks with Natural Earth 110m populated places. This covers global major city names but not a complete global landmark database. Missing work: add a reviewed regional/global landmark fixture pipeline, source attribution, per-region offline packs, richer categories such as mountains/islands/bays/cultural landmarks, higher-detail populated-place packs, and viewport-aware label collision/ranking so labels do not become a wall of text on mobile.
- Night lighting coverage: current night mode uses replay time/local longitude plus route-nearby city points as procedural lights. Missing work: full global night-light texture, weather/cloud darkness variation, seasonal sun position/terminator accuracy, and per-city light intensity calibrated from real night-lights data.
- Runtime adapter split: browser export is behind the adapter; import and native recording handoff are still not fully abstracted behind one runtime-capability layer.
- Photo matching and journal media: iOS/photo matcher pieces exist, but Travel Atlas cards still use generated placeholders.
- Notifications: rules exist, but native notification scheduling is not wired to replay/recording events.
- Native recording to replay handoff: iOS recording/export and Web replay share concepts, but not a seamless recorded-journey-to-WebView payload flow yet.
- iOS CI: workflow has been patched to create `Travel Globe CI` simulator before destination resolution; needs confirmation on GitHub Actions after push.

See `docs/unfinished-features-audit.md` for the longer audit.

## Verification Commands

```bash
npm --prefix replay-engine run prepare:airports
npm --prefix replay-engine run typecheck
npm --prefix replay-engine run test
npm --prefix replay-engine run build
./scripts/copy-replay-to-ios.sh
npm --prefix replay-engine run preview
npm --prefix replay-engine run verify:preview
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild build -project TravelGlobe.xcodeproj -scheme TravelGlobe -destination 'generic/platform=iOS Simulator' -derivedDataPath /private/tmp/TravelGlobeDerived CODE_SIGNING_ALLOWED=NO
```
