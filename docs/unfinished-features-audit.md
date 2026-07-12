# Unfinished Features Audit

Updated: 2026-07-11

This audit tracks features that looked like placeholders, provider shells, or partially wired product modes. It excludes generated Replay Engine build files.

## Addressed This Pass

### Flight preload

- Previous state: `FlightPlanProvider` had an offline fixture lookup and a future `network-provider` source, but no user-facing way to preload a flight.
- Current state: Replay Engine now has a `航班預載` panel. Users can enter only a known flight number such as `CI100`; the offline schedule seed resolves it to `TPE -> NRT`, then the app builds a valid planned `Journey`, loads it into the existing globe replay, creates events, updates Travel Atlas records, and stores it through the browser runtime adapter. Manual origin/destination IATA fields remain available as optional overrides.
- Remaining gap: broad airline schedule/status/airway data still needs a licensed, imported, or configured provider. The first version intentionally uses Great Circle route estimation and later overlays GPS actual track.

### OurAirports airport index

- Previous state: `flight-preload/airportIndex.ts` was a curated in-code list.
- Current state: `scripts/prepare-airport-index.mjs` generates `shared/offline-packs/core-global/airports-index.json` from OurAirports airports/runways/countries/regions CSVs. The index includes IATA/ICAO, coordinates, country/region, municipality, scheduled service, runway count, and longest runway. It also generates `shared/offline-packs/core-global/aviation-context-index.json` from frequencies and navaids, plus `ourairports-manifest.json` with source metadata.
- Remaining gap: the aviation context is visible in product status, but there is not yet a full searchable airport detail UI.

### Natural Earth boundaries and offline manifests

- Previous state: the globe used placeholder border arcs and the core offline pack manifest was fixture-only.
- Current state: `scripts/prepare-geo-data.mjs` extracts Natural Earth 110m coastlines and admin country boundaries into `shared/offline-packs/core-global/geo-boundaries.json`; `createGlobe.ts` renders those lines instead of placeholder arcs. The core manifest now lists Natural Earth and fixture source files with size/hash metadata and generated index paths.
- Remaining gap: higher-detail geometry, label ranking, and spatial indexes are not built yet.

## Still Partial

### Network flight-plan provider

- Evidence: `FlightPlanLookupResult.source` still includes `network-provider`, but no network implementation exists. The current offline schedule seed only contains first-version examples such as `CI100` and `BR190`.
- Impact: unknown flight numbers cannot fetch a true carrier schedule, aircraft, delays, filed route, or waypoints unless the user manually enters origin/destination.
- Next step: add a flight-number schedule source backed by a licensed/imported dataset first; defer paid historical/real-time API until filed routes or historical actual tracks become product requirements.

### Offline packs

- Evidence: `offlinePacks.ts` now references generated Natural Earth / OurAirports manifests and the UI reports installed data layers, but Pack still toggles browser-local state rather than downloading/deleting remote package assets.
- Impact: product state reflects real generated layers, but app storage management is not production-grade yet.
- Next step: package generated indexes as installable assets and wire download/delete paths through native/web runtime capabilities.

### Browser/native runtime split

- Evidence: browser `.travelglobe` and share-safe JSON export now go through `BrowserRuntimeAdapter`, but import and native recording payload handoff are still handled outside one complete runtime contract.
- Impact: Web export is less coupled to UI, but iOS/Web parity is incomplete.
- Next step: move import and native recorded-journey payload loading behind runtime-capability methods and make iOS/web behavior explicit in UI.

### iOS GitHub Actions simulator destination

- Evidence: the latest failed iOS workflow only exposed placeholder simulator destinations on `macos-latest` / Xcode 26.5, so destination resolution failed before tests.
- Current state: `.github/workflows/ios.yml` now creates a named `Travel Globe CI` simulator and resolves that exact destination before running tests.
- Remaining gap: this needs a post-push GitHub Actions confirmation.

### Photo matching and journal media

- Evidence: `PhotoImportService` exists on iOS and `photoMatcher.ts` exists in Replay Engine, but Travel Atlas record cards still use generated visual placeholders rather than real media thumbnails.
- Impact: travel records feel atlas-like, but not yet a true personal photo diary.
- Next step: connect imported photo metadata/media IDs to `TravelRecord` rendering and `.travelglobe` package assets.

### Notifications

- Evidence: `notificationRules.ts` produces replay notification suggestions; iOS manual still frames notification permission as a test path.
- Impact: notifications are visible in product state, but not scheduled as native notifications from replay/recording events.
- Next step: wire notification rules into `TravelNotificationService` with user-controlled permission and scheduling.

### Full native recording to replay handoff

- Evidence: iOS has recording/database/export pieces, while Web Replay Engine currently loads bundled sample or imported/preloaded journeys.
- Impact: live native recording and Web replay are adjacent but not fully unified as a seamless "record then replay this exact journey" flow.
- Next step: export recorded SQLite journey/points into the same `Journey` contract consumed by Replay Engine, then open that payload in the WebView bridge.
