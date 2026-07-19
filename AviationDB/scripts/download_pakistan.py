#!/usr/bin/env python3
"""PK - PCAA AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path

p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "pakistan"
r.mkdir(parents=True, exist_ok=True)

print("PK AIP: https://www.caapakistan.com.pk/")
print("Access may require registration. Check the URL above.")

(r / "manifest.json").write_text(json.dumps({
    "source": "pakistan",
    "provider": "PCAA",
    "country": "PK",
    "source_url": "https://www.caapakistan.com.pk/",
    "source_type": "unknown",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIP access status needs confirmation"],
}, indent=2) + "\n")
