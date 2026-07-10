# Data Model

Travel Globe uses versioned JSON contracts and preserves raw journey evidence.

## Route Boundaries

- `rawRoute`: accepted source points as recorded or imported. This data is never overwritten by smoothing or replay processing.
- `processedRoute`: validated, filtered, and cleaned points derived from the raw route.
- `derivedReplayRoute`: display-ready points used for animation, including interpolated or estimated points where needed.

Estimated or interpolated points must be marked by `source` and must not be presented as measured GPS data.

## Portable Journey

A journey includes:

- `schemaVersion` and `appVersion`
- stable IDs
- UTC timestamps
- segments with route boundary fields
- timeline events
- media references
- optional statistics and display settings
