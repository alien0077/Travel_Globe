# Travel Globe

Every journey deserves a beautiful replay.

Travel Globe is a local-first travel recording and replay system. Phase 0-1 focuses on a standalone offline Replay Engine that can load a realistic Taipei-to-Tokyo sample flight, render it on a procedural 3D globe, and replay the journey without a network connection.

## Current Scope

- Monorepo scaffold for contracts, shared fixtures, docs, scripts, and the Replay Engine.
- Versioned JSON Schema contracts for portable journey data.
- Vite + TypeScript + Three.js standalone Replay Engine prototype.
- Vitest coverage for geodesic distance, bearing, great-circle interpolation, and journey schema validation.
- Browser import for journey JSON and stored `.travelglobe` packages.
- Browser export for `.travelglobe` packages and share-safe redacted JSON.
- Timeline event navigation and nearest-landmark guidance.

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

The current build pushes the browser replay layer as far as this workspace can verify. Native iOS recording, PhotoKit, real geographic datasets, cloud sync, AI journal generation, and production static sharing remain active product work that require additional implementation plus real-device or data-license verification.
