# AviationDB

AviationDB builds a canonical aviation graph for Travel Globe and exports a compact app pack.

The system has two layers:

- Canonical SQLite: source metadata, airports, navigation points, airways, segments, procedures, parser issues, and validation issues.
- App compact pack: region-scoped JSON payloads optimized for Web/iOS route lookup.

Official aviation sources default to `manual_review_required`. Raw official files, full processed databases, and full app packs must not be published until redistribution rights are confirmed.

See [docs/source-acquisition-log.md](docs/source-acquisition-log.md) for the country-by-country download record,
blockers, private raw locations, and validation status.

## Local Commands

```bash
PYTHONPATH=src python3.12 -m aviationdb --help
PYTHONPATH=src python3.12 -m aviationdb build-all
PYTHONPATH=src python3.12 -m aviationdb validate asia-east
PYTHONPATH=src python3.12 -m aviationdb route RCTP RJAA --region asia-east
PYTHONPATH=src python3.12 -m aviationdb export app-pack --region asia-east
```

## Development Checks

```bash
python3.12 -m pytest
python3.12 -m ruff check .
python3.12 -m mypy src
```

If local Python 3.12 does not have dev dependencies installed, install with:

```bash
python3.12 -m pip install -e ".[dev]"
```
