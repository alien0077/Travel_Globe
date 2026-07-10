# Architecture

Travel Globe is split into a thin native recorder, portable contracts, product-mode services, and an offline Replay Engine.

## Layers

- Native Recorder: SwiftUI iOS shell for permissions, CoreLocation-facing recording, SQLite schema setup, PhotoKit imports, notifications, exports, offline pack downloads, and WKWebView bridging.
- Replay Engine: offline HTML, TypeScript, and Three.js application responsible for rendering, replay timing, route visualization, camera behavior, HUD, timeline controls, product-mode summaries, and standalone web viewing.
- Product Services: TypeScript modules for planning, journaling, statistics, time-machine summaries, photo matching, auto recording rules, offline pack state, and travel notifications.
- Shared Contracts: JSON Schema files that define portable journey packages and fixture data.
- Shared Data: sample journeys and fixtures used by the app, tests, and future import/export tools.

## Runtime Rule

The Replay Engine must continue to run without native APIs or network access. Native integration goes through explicit runtime adapters and the versioned bridge protocol, while raw route data remains separate from processed and replay-derived route data.
