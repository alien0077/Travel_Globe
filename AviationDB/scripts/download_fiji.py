#!/usr/bin/env python3
"""(FJ) Fiji CAA AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "fiji"
r.mkdir(parents=True, exist_ok=True)
print("FJ AIP: https://www.example.com/fiji")
(r / "manifest.json").write_text(json.dumps({
    "source": "fiji", "provider": "Fiji CAA", "country": "FJ",
    "source_url": "https://www.example.com/fiji", "source_type": "unknown",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
}, indent=2) + "\n")
