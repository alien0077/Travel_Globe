# Replay Engine

The Replay Engine is a standalone Vite + TypeScript + Three.js app.

## Phase 1 Capabilities

- procedural globe
- atmosphere and star field
- placeholder country-border layer
- Taipei-to-Tokyo flight route
- aircraft marker
- play, pause, timeline scrubber, and speed controls
- global and follow camera modes
- basic flight HUD
- import journey JSON or stored `.travelglobe` packages
- export `.travelglobe` packages
- export share-safe redacted journey JSON
- timeline event navigation
- nearest landmark and window-side guidance

## Determinism

Given the same journey data and replay time, the engine should produce the same route position and HUD state.
