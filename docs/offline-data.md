# Offline Data

The current offline data layer uses NASA Blue Marble imagery, bundled Earth lights/cloud/specular textures, Natural Earth 50m coastline/country boundary geometry, Natural Earth 10m populated places and geography region points, GeoNames cities15000 global city data, OurAirports airport/frequency/navaid indexes, FlightGear GPL v2-or-later global airway graph data, OpenFlights historical route graph context for equipment fallback, small fixture landmarks, and deterministic source manifests.

Run:

```bash
scripts/download-geo-data.sh
npm --prefix replay-engine run prepare:geo
npm --prefix replay-engine run prepare:airports
npm --prefix replay-engine run prepare:aviation
```

The download script writes source archives, CSVs, route data, and texture source copies to `shared/source-data/`. The geo prepare script writes `shared/offline-packs/core-global/manifest.json`, `shared/offline-packs/core-global/geo-boundaries.json`, `shared/offline-packs/core-global/populated-places.json`, `shared/offline-packs/core-global/geography-regions.json`, `shared/offline-packs/core-global/global-places.json`, and `shared/offline-packs/core-global/geo-spatial-index.json`. The airport prepare script transforms OurAirports CSVs and OpenFlights routes into `shared/offline-packs/core-global/airports-index.json`, `shared/offline-packs/core-global/aviation-context-index.json`, and `shared/offline-packs/core-global/ourairports-manifest.json` for offline flight preload, airport lookup, aviation context, and historical route graph summaries. The aviation prepare script publishes only the FlightGear-derived `global.airgraph` pack plus GPL v2 notices under `shared/offline-packs/aviation` and `replay-engine/public/offline-packs/aviation`.

## Offline Refresh Cadence

Some upstream sources update frequently while others are historical snapshots. Travel Globe should not silently ingest those changes every app launch; use a controlled update cadence:

- Weekly automated drift check: `.github/workflows/ourairports-data.yml` runs every Monday at 03:17 UTC and can also be triggered manually. Despite the filename, it now checks the full offline source/core-global pack.
- Monthly reviewed refresh: if the weekly check reports changes, regenerate locally, review the diff, then commit the updated source manifest and generated indexes.
- Urgent manual refresh: use `workflow_dispatch` or run the local commands above when a known airport/code correction matters to a release.

Keep the attribution string in app metadata and About/Data Sources surfaces:

`Airport and runway data provided by OurAirports.`

Keep the GeoNames attribution when global places are surfaced:

`Contains GeoNames data available under CC BY 4.0.`

Keep the OpenFlights route graph attribution when airport route context is surfaced:

`Historical route graph derived from OpenFlights routes.dat; not live schedule or navigation data.`

Keep the FlightGear attribution and GPL v2 notice when airway graph routing is surfaced:

`FlightGear navdata is distributed under GNU GPL v2. See FLIGHTGEAR_LICENSE.txt and licenses/GPL-2.0.txt.`


Future data sources must be evaluated for:

- license compatibility
- attribution requirements
- package size
- update cadence
- offline indexing strategy

The current generated spatial index is a 5-degree JSON grid for route-nearby candidate lookup. SQLite R-Tree or exact point-in-polygon indexes remain reserved for future native/runtime search work once query requirements are fixed.

See `docs/data-sources.md` for the current production source decision.
