# Unfinished Features Audit

Updated: 2026-07-15

This audit tracks features that looked like placeholders, provider shells, or partially wired product modes. It excludes generated Replay Engine build files.

## Addressed This Pass

### Flight preload

- Previous state: `FlightPlanProvider` had an offline fixture lookup and a future `network-provider` source, but no user-facing way to preload a flight.
- Current state: Replay Engine now has a `航班預載` panel. Users can enter a local aviationstack API key in Web or the iOS WebView; successful flight-number lookups are cached locally and reused when the API later fails. Manual origin/destination IATA fields remain available as optional overrides, and the offline seed still resolves first-version examples such as `CI100`.
- Remaining gap: aviationstack free-tier lookups do not provide a full filed airway/waypoint route. The first version intentionally uses Great Circle route estimation and later overlays GPS actual track.

### OurAirports airport index

- Previous state: `flight-preload/airportIndex.ts` was a curated in-code list.
- Current state: `scripts/prepare-airport-index.mjs` generates `shared/offline-packs/core-global/airports-index.json` from OurAirports airports/runways/countries/regions CSVs. The index includes IATA/ICAO, coordinates, country/region, municipality, scheduled service, runway count, and longest runway. It also generates `shared/offline-packs/core-global/aviation-context-index.json` from frequencies and navaids, plus `ourairports-manifest.json` with source metadata. Travel Atlas now renders origin/destination airport detail cards with runway, frequency, and navaid summaries.
- Remaining gap: a larger standalone airport browser/search screen could still be added later, but route-level airport detail is wired.

### Natural Earth boundaries and offline manifests

- Previous state: the globe used placeholder border arcs and the core offline pack manifest was fixture-only.
- Current state: `scripts/prepare-geo-data.mjs` extracts Natural Earth 50m coastlines and admin country boundaries into `shared/offline-packs/core-global/geo-boundaries.json`, 10m populated places into `populated-places.json`, and 10m geography region points into `geography-regions.json`; `createGlobe.ts` renders the higher-detail lines. The core manifest lists Natural Earth and fixture source files with size/hash metadata and generated index paths. Offline pack install/delete state is persisted locally and exposed in Travel Atlas.
- Remaining gap: true spatial indexes and remote per-region package downloads are not built yet.

### Globe lighting and descent detail

- Previous state: day/night was local-time procedural shading with route-nearby city light sprites; clouds were generated canvas marks.
- Current state: the globe uses bundled Earth lights, cloud, and specular textures, with replay-date seasonal sun declination and UTC-based sun direction. Origin/destination airports are rendered as globe labels; they start large at takeoff, shrink as altitude/distance increases, and grow again during descent.
- Remaining gap: this is not a live weather feed. Cloud cover is a realistic static texture with animation, not real-time METAR/satellite weather.

### Runtime, records, and native bridge

- Previous state: Travel Records were mostly prompt-based, browser history was hidden in localStorage, and iOS notifications/photo data were adjacent but not fully visible in Replay Engine.
- Current state: `BrowserRuntimeAdapter` lists/loads/deletes local journeys; Travel Atlas exposes that history. iOS can queue the latest SQLite journey into Replay Engine after relaunch, Web notification rules can call native `notification.schedule`, and Travel Records support local photo attachments, thumbnails, region/time edits, and undo.
- Remaining gap: a full native runtime adapter, binary media packaging, cross-device sync, and richer delayed/geofence notification triggers are still future work.

## Still Partial

### Network flight-plan provider

- Evidence: aviationstack lookup is implemented for local user-provided API keys, but the app still does not ingest paid schedule/route products or filed waypoints.
- Impact: unknown flight numbers can often fill origin/destination from aviationstack real-time data, but exact seasonal schedules, historical records, filed routes, delays, gates, and waypoints remain limited by plan/data availability.
- Next step: add a licensed schedule/route source or paid aviationstack endpoints only when those fields become product requirements.

### Offline packs

- Evidence: `offlinePacks.ts` now references generated Natural Earth / OurAirports manifests, persists local install/delete state, and Travel Atlas exposes Core Global Atlas / East Asia Flight Context controls.
- Impact: product state reflects real generated layers and local user choice, but app storage management is not a production remote package installer yet.
- Next step: package generated indexes as installable assets and wire download/delete paths through native/web runtime capabilities.

### Browser/native runtime split

- Evidence: browser `.travelglobe`, share-safe JSON export, saved journey list/load/delete, and iOS latest-SQLite replay queue now go through explicit adapter/bridge paths.
- Impact: Web history is usable and native relaunch handoff exists, but the native layer still does not replace browser localStorage as a complete runtime adapter.
- Next step: formalize a `NativeRuntimeAdapter` for full journey CRUD/import/export parity.

### iOS GitHub Actions simulator destination

- Evidence: the latest failed iOS workflow only exposed placeholder simulator destinations on `macos-latest` / Xcode 26.5, so destination resolution failed before tests.
- Current state: `.github/workflows/ios.yml` now creates a named `Travel Globe CI` simulator and resolves that exact destination before running tests.
- Remaining gap: this needs a post-push GitHub Actions confirmation.

### Photo matching and journal media

- Evidence: `PhotoImportService` can create PhotoKit GPS visit points, and Web Travel Records can attach local photos and render thumbnails.
- Impact: travel records can now show user media locally, but native picker thumbnails and package/export privacy review remain future work.
- Next step: connect native PhotoKit asset thumbnails/full image export to `.travelglobe` package assets with per-photo privacy controls.

### Notifications

- Evidence: `notificationRules.ts` produces replay notification suggestions, and Web now sends `notification.schedule` bridge messages to `TravelNotificationService`.
- Impact: native local scheduling is wired for current rules; richer timing, geofencing, and recording-phase reminders are still product work.
- Next step: add user controls for reminder categories and delayed/geofence triggers.

### Full native recording to replay handoff

- Evidence: iOS sends live/completed recording payloads and can queue the latest SQLite journey into Replay Engine after relaunch.
- Impact: planned-flight recordings can round-trip into Web Replay; a fully native-created GPS-only journey still relies on the current Web journey shell.
- Next step: build a native-to-Web `Journey` serializer for GPS-only journeys without a preloaded flight plan.
