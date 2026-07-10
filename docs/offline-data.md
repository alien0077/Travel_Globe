# Offline Data

The current offline data layer uses procedural visuals, small fixture landmarks, and a deterministic core offline pack manifest generated from local fixtures.

Run:

```bash
node scripts/prepare-geo-data.mjs
```

This writes `shared/offline-packs/core-global/manifest.json`. The manifest is intentionally marked `project-fixture-only` so production builds cannot mistake fixture labels or placeholder borders for licensed geographic data.

Future data sources must be evaluated for:

- license compatibility
- attribution requirements
- package size
- update cadence
- offline indexing strategy

SQLite R-Tree indexes are reserved for licensed geographic search and label ranking work once production data sources are selected.

See `docs/data-sources.md` for the current production source decision.
