#!/usr/bin/env python3
"""IL - CAA Israel AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path

p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "israel"
r.mkdir(parents=True, exist_ok=True)

print("IL AIP: https://e-aip.azurefd.net/")
print("Access may require registration. Check the URL above.")

(r / "manifest.json").write_text(json.dumps({
    "source": "israel",
    "provider": "CAA Israel",
    "country": "IL",
    "source_url": "https://e-aip.azurefd.net/",
    "source_type": "unknown",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIP access status needs confirmation"],
}, indent=2) + "\n")
