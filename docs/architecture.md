# Architecture

Travel Globe is split into a thin native recorder and a portable Replay Engine.

## Layers

- Native Recorder: future iOS shell for permissions, CoreLocation, SQLite persistence, PhotoKit, notifications, exports, and WKWebView bridging.
- Replay Engine: offline HTML, TypeScript, and Three.js application responsible for rendering, replay timing, route visualization, camera behavior, HUD, and standalone web viewing.
- Shared Contracts: JSON Schema files that define portable journey packages and fixture data.
- Shared Data: sample journeys and fixtures used by the app, tests, and future import/export tools.

## Phase 0-1 Rule

The Replay Engine must not depend on native APIs. Native integration begins in a later phase through explicit runtime adapters and a versioned bridge protocol.
