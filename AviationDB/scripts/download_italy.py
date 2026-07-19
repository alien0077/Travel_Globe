#!/usr/bin/env python3
"""IT - ENAV AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path

p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "italy"
r.mkdir(parents=True, exist_ok=True)

print("IT AIP: https://www.enav.it/")
print("Access may require registration. Check the URL above.")

(r / "manifest.json").write_text(json.dumps({
    "source": "italy",
    "provider": "ENAV",
    "country": "IT",
    "source_url": "https://www.enav.it/",
    "source_type": "unknown",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIP access status needs confirmation"],
}, indent=2) + "\n")
