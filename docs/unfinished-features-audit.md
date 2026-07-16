# Unfinished Features Audit

Updated: 2026-07-15

This audit tracks features that looked like placeholders, provider shells, or partially wired product modes. It excludes generated Replay Engine build files.

## Addressed This Pass

### Flight preload

- Previous state: `FlightPlanProvider` had an offline fixture lookup and a future `network-provider` source, but no user-facing way to preload a flight.
- Current state: Replay Engine now has a `航班預載` panel. Users can enter a local aviationstack API key in Web or the iOS WebView; successful flight-number lookups are cached locally and reused when the API later fails. Manual origin/destination IATA fields remain available as optional overrides, and the offline seed still resolves first-version examples such as `CI100`. OpenFlights `routes.dat` is downloaded into source data and transformed into airport route graph context plus route-specific equipment-code fallback for missing aircraft types.
- Remaining gap: aviationstack free-tier lookups and OpenFlights do not provide a full filed airway/waypoint route or current timetable. OpenFlights does not replace origin/destination/time/airline or route geometry; the planned line is still endpoint interpolation until a filed-route/waypoint provider is added. GPS actual track overlays the real flown path.

### OurAirports airport index

- Previous state: `flight-preload/airportIndex.ts` was a curated in-code list.
- Current state: `scripts/prepare-airport-index.mjs` generates `shared/offline-packs/core-global/airports-index.json` from OurAirports airports/runways/countries/regions CSVs. The index includes IATA/ICAO, coordinates, country/region, municipality, scheduled service, runway count, and longest runway. It also generates `shared/offline-packs/core-global/aviation-context-index.json` from frequencies, navaids, and OpenFlights historical route graph summaries, plus `ourairports-manifest.json` with source metadata. Travel Atlas now renders origin/destination airport detail cards and a searchable airport browser.
- Remaining gap: none for the first large airport browser/search screen; deeper native-style browsing can be product polish later.

### Natural Earth boundaries and offline manifests

- Previous state: the globe used placeholder border arcs and the core offline pack manifest was fixture-only.
- Current state: `scripts/prepare-geo-data.mjs` extracts Natural Earth 50m coastlines and admin country boundaries into `shared/offline-packs/core-global/geo-boundaries.json`, 10m populated places into `populated-places.json`, and 10m geography region points into `geography-regions.json`; `createGlobe.ts` renders the higher-detail lines. The core manifest lists Natural Earth and fixture source files with size/hash metadata and generated index paths. Offline pack install/delete state is persisted locally and exposed in Travel Atlas.
- Remaining gap: exact point-in-polygon queries are still future work; the generated grid index narrows candidates but does not yet answer polygon containment by itself.

### GeoNames global places and spatial grid

- Previous state: route-nearby labels merged curated fixtures with Natural Earth populated places/geography regions, but there was no downloaded global place pipeline beyond Natural Earth and no generated spatial candidate index.
- Current state: `scripts/download-geo-data.sh` downloads GeoNames `cities15000.zip`; `npm --prefix replay-engine run prepare:geo` builds `global-places.json` with 41,583 merged features and `geo-spatial-index.json` with 2,187 5-degree cells. Runtime landmark filtering now uses the spatial grid before distance checks.
- Remaining gap: GeoNames covers cities/populated places, not reviewed tourism POI categories. Rich category datasets and per-region payload splitting remain future work.

### Globe lighting and descent detail

- Previous state: day/night was local-time procedural shading with route-nearby city light sprites; clouds were generated canvas marks.
- Current state: the globe uses bundled Earth lights, cloud, and specular textures, with replay-date seasonal sun declination and UTC-based sun direction. Origin/destination airports are rendered as globe labels; they start large at takeoff, shrink as altitude/distance increases, and grow again during descent. Cloud opacity now varies deterministically from replay position/time as a simulated cloud-cover layer.
- Remaining gap: this is not a live weather feed. NOAA AviationWeather METAR/TAF, Open-Meteo cloud-cover forecasts, or NASA GIBS satellite tiles can be added later when live network weather becomes a product requirement.

### Runtime, records, and native bridge

- Previous state: Travel Records were mostly prompt-based, browser history was hidden in localStorage, and iOS notifications/photo data were adjacent but not fully visible in Replay Engine.
- Current state: `BrowserRuntimeAdapter` lists/loads/deletes local journeys; Travel Atlas exposes that history. iOS can queue the latest SQLite journey into Replay Engine after relaunch, Web notification rules can call native `notification.schedule`, and Travel Records support local photo attachments, thumbnails, region/time edits, and undo.
- Remaining gap: a full native runtime adapter, binary media packaging, cross-device sync, and richer delayed/geofence notification triggers are still future work.

### Native GPS-only replay handoff

- Previous state: completed iOS recordings without a Web flight-plan ID were applied to whatever Replay Engine journey was currently loaded, so a fully native GPS-only recording still depended on the Web journey shell.
- Current state: Replay Engine now converts a GPS-only `recording.completed` payload into a standalone `Journey` with native-derived journey/segment IDs, raw/processed/replay routes from CoreLocation points, start/stop timeline events, and distance/GPS count metadata. One-point recordings now keep the real GPS point and add a short estimated replay point; zero-point recordings with flight airport metadata use an airport anchor instead of being dropped.
- Remaining gap: zero-point recordings without any coordinate or airport metadata still cannot create a meaningful map location.

### iOS GitHub Actions simulator destination

- Previous state: the workflow created a named simulator, but full simulator tests could still be skipped or fail to resolve when `xcodebuild -showdestinations` returned empty output for that name.
- Current state: `.github/workflows/ios.yml` now preserves the simulator UDID from `simctl`, boots it before destination resolution, and falls back to `platform=iOS Simulator,id=<udid>` when `-showdestinations` omits the named destination.
- Remaining gap: this still needs a pushed GitHub Actions run to confirm behavior on the hosted macOS runner.

## Still Partial

### Network flight-plan provider

- Evidence: aviationstack lookup is implemented for local user-provided API keys, and OpenFlights historical route graph is now bundled for airport context plus missing-aircraft equipment-code fallback. The app still does not ingest paid schedule/route products or filed waypoints.
- Impact: unknown flight numbers can often fill origin/destination from aviationstack real-time data, and airports can show historical route graph context offline, but exact seasonal schedules, historical records, filed routes, delays, gates, and waypoints remain limited by licensed data availability.
- Next step: add a licensed schedule/route source or paid aviationstack endpoints only when those fields become product requirements.

### Offline packs

- Evidence: `offlinePacks.ts` now references generated Natural Earth / GeoNames / OurAirports/OpenFlights manifests, persists local install/delete state, and Travel Atlas exposes Core Global Atlas / East Asia Flight Context controls. The weekly GitHub Action now refresh-checks the full source/core-global pack instead of only the airport index.
- Impact: product state reflects real generated layers and local user choice without requiring a remote package downloader.
- Next step: keep using scheduled drift checks and reviewed commits for offline data refreshes.

### Browser/native runtime split

- Evidence: browser `.travelglobe`, share-safe JSON export, saved journey list/load/delete, iOS latest-SQLite replay queue, and GPS-only native replay journey creation now go through explicit adapter/bridge paths.
- Impact: Web history is usable and native relaunch/GPS-only handoff exists, but the native layer still does not replace browser localStorage as a complete runtime adapter.
- Next step: formalize a `NativeRuntimeAdapter` for full journey CRUD/import/export parity.

### Photo matching and journal media

- Evidence: `PhotoImportService` can create PhotoKit GPS visit points, and Web Travel Records can attach local photos and render thumbnails.
- Impact: travel records can now show user media locally, but native picker thumbnails and package/export privacy review remain future work.
- Next step: connect native PhotoKit asset thumbnails/full image export to `.travelglobe` package assets with per-photo privacy controls.

### Notifications

- Evidence: `notificationRules.ts` produces replay notification suggestions, and Web now sends `notification.schedule` bridge messages to `TravelNotificationService`.
- Impact: native local scheduling is wired for current rules; richer timing, geofencing, and recording-phase reminders are still product work.
- Next step: add user controls for reminder categories and delayed/geofence triggers.
