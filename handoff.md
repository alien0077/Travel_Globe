# Travel Globe Handoff

Updated: 2026-07-11

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
- airport-frequencies.csv: downloaded for future airport detail views
- countries.csv / regions.csv: readable country and admin-region labels
- navaids.csv: downloaded for future aviation context, not used by route drawing yet

Attribution to show in About / Data Sources:

`Airport and runway data provided by OurAirports.`

Implemented files:

- `scripts/download-geo-data.sh`
- `scripts/prepare-airport-index.mjs`
- `shared/offline-packs/core-global/airports-index.json`
- `replay-engine/src/flight-preload/airportIndex.ts`

### Flight Number Source

First version does not require a paid flight API. The app resolves known flight numbers from an offline schedule seed:

- `CI100`: China Airlines, `TPE -> NRT`, default duration 185 minutes
- `BR190`: EVA Air, `TPE -> HND`, default duration 190 minutes

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
- Great Circle planned route generation with replay, processed, and raw routes.
- Preview verification for `CI100` preload without manually entering origin/destination.
- GitHub Actions drift check for OurAirports source/index changes.

## Still Partial

These are the main half-finished areas to continue next:

- Network flight-plan provider: source type exists, but no API implementation or key-management path is wired.
- Flight schedule coverage: only a seed schedule index exists; broad flight-number lookup needs an imported or licensed schedule source.
- Frequencies and navaids: downloaded, but not transformed into searchable app indexes or airport detail UI.
- Offline packs: pack install state exists, but most transformed data layers are still product scaffolding.
- Geographic borders: globe still needs real Natural Earth coastline/country geometry rather than placeholder visual layers.
- Runtime adapter split: browser import/export and native recording are not fully abstracted behind one runtime-capability layer.
- Photo matching and journal media: iOS/photo matcher pieces exist, but Travel Atlas cards still use generated placeholders.
- Notifications: rules exist, but native notification scheduling is not wired to replay/recording events.
- Native recording to replay handoff: iOS recording/export and Web replay share concepts, but not a seamless recorded-journey-to-WebView payload flow yet.

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
