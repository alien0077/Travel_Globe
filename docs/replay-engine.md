# Replay Engine

The Replay Engine is a standalone Vite + TypeScript + Three.js app.

## Capabilities

- procedural globe
- atmosphere and star field
- placeholder country-border layer
- Taipei-to-Tokyo flight route
- offline flight preload from flight number, origin/destination IATA, departure time, and duration
- aircraft marker
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
- installable offline pack state placeholder
- desktop and mobile Playwright production-build verification

## Determinism

Given the same journey data and replay time, the engine should produce the same route position and HUD state.

## Product Modes

Product modes are implemented as deterministic TypeScript services first. They do not require network access, native iOS APIs, or real third-party data licenses. This keeps the replay shell usable while later phases replace fixtures and placeholders with verified production sources.
