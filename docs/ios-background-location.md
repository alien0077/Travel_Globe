# iOS Background Location

iOS background recording is intentionally out of scope for Phase 0-1.

When Phase 3 begins, the implementation must verify current Apple CoreLocation behavior for:

- When In Use and Always authorization
- reduced-accuracy authorization
- background location capability
- `allowsBackgroundLocationUpdates`
- low-power mode
- termination and restart recovery limits

The WebView must never be the canonical recorder.
