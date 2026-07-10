# Travel Globe

Every journey deserves a beautiful replay.

Travel Globe is a local-first travel recording and replay system. Phase 0-1 focuses on a standalone offline Replay Engine that can load a realistic Taipei-to-Tokyo sample flight, render it on a procedural 3D globe, and replay the journey without a network connection.

## Current Scope

- Monorepo scaffold for contracts, shared fixtures, docs, scripts, and the Replay Engine.
- Versioned JSON Schema contracts for portable journey data.
- Vite + TypeScript + Three.js standalone Replay Engine prototype.
- Vitest coverage for geodesic distance, bearing, great-circle interpolation, and journey schema validation.

## Commands

```bash
npm --prefix replay-engine install
npm --prefix replay-engine run typecheck
npm --prefix replay-engine run test
npm --prefix replay-engine run build
npm --prefix replay-engine run preview
```

The production build uses relative asset paths so `replay-engine/dist` can be served from static hosting or opened by an offline-capable local server.

## Phase Boundary

This phase intentionally does not implement CoreLocation, native iOS recording, PhotoKit, AI journal generation, real geographic datasets, cloud sync, or static web sharing. Those features begin after the replay prototype is stable.
