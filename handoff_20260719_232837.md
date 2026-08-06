# Travel Globe Handoff

Updated: 2026-07-15

## Current Direction

Travel Globe is moving from a pure replay globe toward a Travel Atlas experience:

- planned flight route before departure
- actual GPS track during flight
- travel records generated from flight events and future media/GPS context
- editable travel record overlay that does not mutate raw GPS points
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

### Planned Route Fallback

When no real filed route is available, Travel Globe uses Great Circle interpolation for the planned route. OpenFlights `routes.dat` is not used as route geometry because it does not include waypoints. If a matching origin-destination pair exists and no aircraft type came from aviationstack/cache/user input, Travel Globe may use the OpenFlights equipment code as the aircraft fallback only. This is enough for the first Planned vs Actual experience:

- Planned: offline schedule plus OurAirports coordinates
- Actual: GPS points collected during flight or imported after the trip

Paid flight APIs remain deferred. They are only needed when the product requires real-time status, historical actual tracks, filed route strings, ATC waypoints, aircraft registration, or delay/cancel data.

## Offline Data Refresh Cadence

Travel Globe refreshes offline source data with review, not silently in app runtime:

- Weekly drift check: `.github/workflows/ourairports-data.yml` runs Monday 03:17 UTC and now checks the full offline source/core-global pack.
- Manual refresh: trigger the workflow with `workflow_dispatch` before a release or when an airport/code correction matters.
- Reviewed monthly refresh: if the weekly check reports a diff, run the local refresh commands, inspect generated source/index/public-pack diffs, then commit.

Local refresh:

```bash
scripts/download-geo-data.sh
npm --prefix replay-engine run prepare:airports
npm --prefix replay-engine run prepare:geo
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
- Planned route generation with Great Circle fallback, plus replay, processed, and raw routes.
- Preview verification for `CI100` preload without manually entering origin/destination.
- GitHub Actions drift check for OurAirports source/index changes.
- GitHub Actions iOS workflow now creates a named simulator before resolving the test destination.
- iOS flight plan bridge: `套用航線` sends the current Web flight plan to native as pending recording metadata.
- iOS now keeps multiple applied flight plans and exposes a native `Record Into` picker; selecting one sends `flightPlan.selected` so Replay Engine switches to that route before GPS recording.
- Native GPS recording now persists Web `segmentId` on real GPS points and sends completed recording payloads back to Replay Engine.
- Native visit points now support one-shot `GPS打卡` and PhotoKit `照片打卡`; both persist in SQLite `visit_points` and sync to Replay Engine as Travel Records without mutating raw GPS tracks.
- Travel Records can be manually added, edited, hidden, and have flight summary metadata corrected through an overlay; raw SQLite GPS remains read-only.
- App manual now documents the full flight-plan-to-GPS-to-Travel-Records workflow and bundled aircraft model attribution.
- aviationstack key entry is available in the Web/iOS Replay Engine preload panel; keys and successful flight lookups are stored locally, and failed future lookups fall back to flight history cache before offline seeds/manual IATA.
- OpenFlights `routes.dat` is downloaded into `shared/source-data/openflights/` and transformed into historical route graph summaries inside `aviation-context-index.json`; matching origin-destination preloads can use its equipment code to fill a missing aircraft type. It is still not a live timetable, waypoint geometry, or filed route source, and it does not override aviationstack origin/destination/time/airline data.
- Natural Earth core geography is refreshed to 50m coastlines/country borders plus 10m populated places and geography region points.
- GeoNames `cities15000.zip` is downloaded into `shared/source-data/geonames/` and transformed into `shared/offline-packs/core-global/global-places.json`.
- Core Global Atlas now includes `geo-spatial-index.json`, a 5-degree grid over global places and boundary-line bounding boxes for route-nearby candidate lookup.
- Globe rendering now uses bundled Earth lights/cloud/specular textures, seasonal UTC sun direction, and airport labels that scale down after takeoff and grow again during descent.
- Travel Atlas now shows origin/destination airport detail cards with runway counts, radio frequencies, and nearby navaids from the generated OurAirports aviation context index.
- Offline pack install/delete state is persisted in local browser storage and exposed in Travel Atlas for the Core Global Atlas and East Asia Flight Context packs.
- Browser runtime adapter now lists, loads, and deletes locally saved journeys, making historical `.travelglobe` sessions visible from Travel Atlas instead of only hidden in localStorage.
- iOS can queue the latest SQLite journey back into Replay Engine after relaunch via `載入最新紀錄`, and Web notifications can request native local scheduling through `notification.schedule`.
- Travel Records now support local photo attachments, thumbnail display, manual region/time edits, and one-step undo while preserving raw GPS/events.
- GPS-only native recordings without a preloaded flight plan now create a standalone Replay Engine `Journey` from the iOS CoreLocation payload instead of mutating the currently loaded sample/web journey.
- GPS-only native recordings with one real point now remain replayable by adding a short estimated point; zero-point recordings with flight airport metadata use an airport anchor instead of being dropped.
- GitHub Actions iOS workflow now carries the simulator UDID from `simctl`, boots the named simulator before destination resolution, and falls back to an explicit UDID destination when `xcodebuild -showdestinations` omits the named simulator.
- GitHub Actions offline data workflow now runs `prepare:airports`, `prepare:geo`, tests, and build against `shared/source-data`, `shared/offline-packs/core-global`, and `replay-engine/public/offline-packs/core-global`.
- Travel Atlas now includes a searchable airport browser with scheduled-service filtering, runway/frequency/navaid counts, and OpenFlights historical route graph context.
- Globe cloud opacity now varies from replay position/time through an offline simulated cloud-cover model; live METAR/satellite weather remains an optional provider layer.

## Still Partial

These items now depend on external data products, post-push validation, or larger future scope:

- Network flight-plan provider: aviationstack real-time lookup and OpenFlights equipment-code fallback are implemented, but exact filed routes/waypoints and paid schedule/history products remain unwired.
- Flight schedule coverage: aviationstack can fill many live flight-number origin/destination pairs when the user provides a key; OpenFlights can show historical route graph context; broad offline flight-number schedule lookup still needs an imported or licensed schedule source because public airport/place/route datasets do not include airline timetable rights.
- Flight schedule accuracy: FD234/FD235 still depend on the offline seed unless aviationstack returns live data; exact seasonal schedule, operating days, aircraft substitutions, and multi-leg `DMK-KHH-NRT` / `NRT-KHH-DMK` modeling still need an API response or reviewed timetable import.
- Geographic borders: Natural Earth 50m coastlines/country boundaries now render on the globe, and a generated grid spatial index is available for candidate lookup. Exact point-in-polygon query logic remains future work.
- Landmark/place coverage: current labels merge curated East Asia/Southeast Asia landmarks, Natural Earth 10m populated places/geography regions, and GeoNames cities15000. Missing work: reviewed category-rich landmark datasets beyond city/place names, per-region offline packs, and deeper mobile label ranking.
- Night lighting coverage: current night mode uses bundled Earth lights/cloud/specular textures plus seasonal sun direction, route-nearby city points, and simulated cloud-cover variation. Missing work: live weather/satellite cloud updates and calibrated per-city light intensity from a dedicated VIIRS night-lights dataset.
- Runtime adapter split: browser history, iOS latest-SQLite replay handoff, and GPS-only native journey loading exist; a fully separate native runtime adapter that replaces browser localStorage remains future architecture work.
- Photo matching and journal media: PhotoKit GPS can create `照片打卡`, and Web records can attach/show local photo thumbnails. Missing work: native explicit picker thumbnails, `.travelglobe` binary media packaging, and share/export privacy review UI.
- Notifications: Web rules now request native local scheduling; richer recording-phase reminders and delayed/geofence triggers remain future work.
- Travel record editing: records can be added, edited, hidden, reclassified, time-adjusted, photo-attached, and undone. Missing work: drag-to-reassign journey/segment, cross-device sync, and a fully polished native-style list editor.
- iOS CI post-push validation: simulator destination fallback is tightened locally, but the updated workflow still needs a pushed GitHub Actions run to confirm hosted runner behavior.
- Zero-point native recordings without any GPS coordinate or airport metadata still cannot create a meaningful map location.

See `docs/unfinished-features-audit.md` for the longer audit.

## Verification Commands

```bash
npm --prefix replay-engine run prepare:airports
npm --prefix replay-engine run prepare:geo
npm --prefix replay-engine run typecheck
npm --prefix replay-engine run test
npm --prefix replay-engine run build
./scripts/copy-replay-to-ios.sh
npm --prefix replay-engine run preview
npm --prefix replay-engine run verify:preview
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild build -project TravelGlobe.xcodeproj -scheme TravelGlobe -destination 'generic/platform=iOS Simulator' -derivedDataPath /private/tmp/TravelGlobeDerived CODE_SIGNING_ALLOWED=NO
```
