# Replay Engine

The Replay Engine is a standalone Vite + TypeScript + Three.js app.

## Capabilities

- procedural globe
- atmosphere and star field
- Natural Earth 110m coastline and country-border layer
- Taipei-to-Tokyo flight route
- offline flight preload from flight number, origin/destination IATA, departure time, and duration
- aircraft marker with a licensed offline aircraft model library for A320, A321, B737, B767, B777, B787, A350, and A380 slots
- play, pause, timeline scrubber, and speed controls
- global and follow camera modes
- basic flight HUD
- import journey JSON or stored `.travelglobe` packages
- export `.travelglobe` packages
- export share-safe redacted journey JSON
- timeline event navigation
- nearest landmark and window-side guidance
- Travel Atlas panels for flight preload, travel records, plan, journal, time machine, statistics, offline packs, auto recording, and notifications
- journal markdown export
- installable offline pack state backed by generated Natural Earth and OurAirports manifests
- desktop and mobile Playwright production-build verification

## Determinism

Given the same journey data and replay time, the engine should produce the same route position and HUD state.

## Product Modes

Product modes are implemented as deterministic TypeScript services first. They do not require network access, native iOS APIs, or paid third-party data licenses. This keeps the replay shell usable while later phases replace seed schedules and local state toggles with broader licensed data and production package delivery.

## Aircraft Models

The canonical model manifest is `replay-engine/public/models/aircraft/library.json`. Runtime loading accepts only ready entries that are GLB/glTF, CC0 or CC BY, commercially usable, derivative-friendly, non-editorial, locally bundled, and within the 500-40k polygon budget for the active LOD. The app must retain author, license, model URL, and Sketchfab source attribution anywhere the model is used.

For the first fleet pass, download Sketchfab models manually from the logged-in web UI, then import each GLB with `npm --prefix replay-engine run import:aircraft-model -- --aircraft <slug> --file <path>`. Use `npm --prefix replay-engine run prepare:aircraft-models -- --dry-run` only to audit public metadata and confirm the candidate list still reports CC Attribution.

The bundled first-fleet livery is Alien Air: red base paint, white `ALIEN AIR` fuselage lettering, wing labels, and a tail `AA` mark. Rebuild it from the downloaded source GLBs with `npm --prefix replay-engine run apply:alien-air-livery -- --all`. All eight first-fleet entries are under the 40k active LOD budget and marked `ready`; high-detail source models such as `a320-200`, `a321neo`, and `b777-300er` use a stronger decimation pass before repainting.
