#!/usr/bin/env python3
"""FR - DSNA/SIA AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path

p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "france"
r.mkdir(parents=True, exist_ok=True)

print("FR AIP: https://www.sia.aviation-civile.gouv.fr/")
print("Access may require registration. Check the URL above.")

(r / "manifest.json").write_text(json.dumps({
    "source": "france",
    "provider": "DSNA/SIA",
    "country": "FR",
    "source_url": "https://www.sia.aviation-civile.gouv.fr/",
    "source_type": "unknown",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIP access status needs confirmation"],
}, indent=2) + "\n")
