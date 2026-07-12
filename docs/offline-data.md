# Offline Data

The current offline data layer uses NASA Blue Marble imagery, Natural Earth 110m coastline/country boundary geometry, OurAirports airport/frequency/navaid indexes, small fixture landmarks, and deterministic source manifests.

Run:

```bash
scripts/download-geo-data.sh
node scripts/prepare-geo-data.mjs
npm --prefix replay-engine run prepare:airports
```

The download script writes source archives and CSVs to `shared/source-data/`. The geo prepare script writes `shared/offline-packs/core-global/manifest.json` and `shared/offline-packs/core-global/geo-boundaries.json`. The airport prepare script transforms OurAirports CSVs into `shared/offline-packs/core-global/airports-index.json`, `shared/offline-packs/core-global/aviation-context-index.json`, and `shared/offline-packs/core-global/ourairports-manifest.json` for offline flight preload, airport lookup, and aviation context.

## OurAirports Refresh Cadence

OurAirports publishes CSV updates daily. Travel Globe should not silently ingest those changes every app launch; use a controlled update cadence:

- Weekly automated drift check: `.github/workflows/ourairports-data.yml` runs every Monday at 03:17 UTC and can also be triggered manually.
- Monthly reviewed refresh: if the weekly check reports changes, regenerate locally, review the diff, then commit the updated source manifest and airport index.
- Urgent manual refresh: use `workflow_dispatch` or run the local commands above when a known airport/code correction matters to a release.

Keep the attribution string in app metadata and About/Data Sources surfaces:

`Airport and runway data provided by OurAirports.`

Future data sources must be evaluated for:

- license compatibility
- attribution requirements
- package size
- update cadence
- offline indexing strategy

SQLite R-Tree indexes are reserved for licensed geographic search and label ranking work once production data sources are selected.

See `docs/data-sources.md` for the current production source decision.
