#!/usr/bin/env python3
"""MA - ONDA AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path

p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "morocco"
r.mkdir(parents=True, exist_ok=True)

print("MA AIP: https://www.onda.ma/")
print("Access may require registration. Check the URL above.")

(r / "manifest.json").write_text(json.dumps({
    "source": "morocco",
    "provider": "ONDA",
    "country": "MA",
    "source_url": "https://www.onda.ma/",
    "source_type": "unknown",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIP access status needs confirmation"],
}, indent=2) + "\n")
