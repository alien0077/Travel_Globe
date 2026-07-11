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
- Current state: `scripts/prepare-airport-index.mjs` generates `shared/offline-packs/core-global/airports-index.json` from OurAirports airports/runways/countries/regions CSVs. The index includes IATA/ICAO, coordinates, country/region, municipality, scheduled service, runway count, and longest runway. `scripts/download-geo-data.sh` now also downloads frequencies.
- Remaining gap: frequencies and navaids are downloaded but not yet transformed into searchable app indexes.

## Still Partial

### Network flight-plan provider

- Evidence: `FlightPlanLookupResult.source` still includes `network-provider`, but no network implementation exists. The current offline schedule seed only contains first-version examples such as `CI100` and `BR190`.
- Impact: unknown flight numbers cannot fetch a true carrier schedule, aircraft, delays, filed route, or waypoints unless the user manually enters origin/destination.
- Next step: add a flight-number schedule source backed by a licensed/imported dataset first; defer paid historical/real-time API until filed routes or historical actual tracks become product requirements.

### Offline packs

- Evidence: `docs/offline-data.md` says pack manifests are `project-fixture-only`; `offlinePacks.ts` tracks installed state but does not install transformed data indexes.
- Impact: the Pack control is useful as product-state scaffolding, but not yet a real offline data installer.
- Next step: transform Natural Earth / OurAirports data into app-ready indexes and make pack install state feed the map/search layers.

### Placeholder borders and geographic layers

- Evidence: `docs/replay-engine.md` still lists a placeholder country-border layer.
- Impact: the globe looks good, but borders are decorative arcs rather than real country/coastline geometry.
- Next step: render Natural Earth coastline/country boundaries from prepared offline data.

### Browser/native runtime split

- Evidence: `BrowserRuntimeAdapter.exportJourney()` throws because browser export is handled directly, and browser capability text says native recording is only available in iOS.
- Impact: workable for Web, but runtime adapters are not yet the single abstraction for import/export/recording.
- Next step: move export/import operations behind runtime-capability methods and make iOS/web behavior explicit in UI.

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
