# Privacy

Travel Globe treats travel data as sensitive personal data.

## Baseline Rules

- Local-first storage.
- No account required.
- No mandatory cloud service.
- No silent uploads.
- No API keys in source code.
- No exact private coordinates in production logs.
- Shared packages must support redaction before public export.

Phase 0-1 uses synthetic fixture data only.

## Implemented Sharing Controls

- Share-safe JSON export removes media references by default.
- First and last route points are coordinate-rounded for endpoint privacy.
- Export metadata records that the journey copy has been redacted.
