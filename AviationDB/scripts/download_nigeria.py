#!/usr/bin/env python3
"""NG - NCAA AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path

p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "nigeria"
r.mkdir(parents=True, exist_ok=True)

print("NG AIP: https://ncaa.gov.ng/")
print("Access may require registration. Check the URL above.")

(r / "manifest.json").write_text(json.dumps({
    "source": "nigeria",
    "provider": "NCAA",
    "country": "NG",
    "source_url": "https://ncaa.gov.ng/",
    "source_type": "unknown",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIP access status needs confirmation"],
}, indent=2) + "\n")
