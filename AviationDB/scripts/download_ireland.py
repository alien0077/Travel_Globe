#!/usr/bin/env python3
"""(IE) IAA Ireland AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "ireland"
r.mkdir(parents=True, exist_ok=True)
print("IE AIP: https://www.example.com/ireland")
(r / "manifest.json").write_text(json.dumps({
    "source": "ireland", "provider": "IAA Ireland", "country": "IE",
    "source_url": "https://www.example.com/ireland", "source_type": "unknown",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
}, indent=2) + "\n")
