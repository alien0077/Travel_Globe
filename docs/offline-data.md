# Offline Data

The current offline data layer uses procedural visuals, small fixture landmarks, and a deterministic core offline pack manifest generated from local fixtures.

Run:

```bash
scripts/download-geo-data.sh
node scripts/prepare-geo-data.mjs
```

The download script writes source archives and CSVs to `shared/source-data/`. The prepare script writes `shared/offline-packs/core-global/manifest.json`. The pack manifest is intentionally marked `project-fixture-only` until the downloaded source data is transformed into app-ready indexes.

Future data sources must be evaluated for:

- license compatibility
- attribution requirements
- package size
- update cadence
- offline indexing strategy

SQLite R-Tree indexes are reserved for licensed geographic search and label ranking work once production data sources are selected.

See `docs/data-sources.md` for the current production source decision.
