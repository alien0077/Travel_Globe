#!/usr/bin/env python3
"""(JO) JACC Jordan AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "jordan"
r.mkdir(parents=True, exist_ok=True)
print("JO AIP: https://www.example.com/jordan")
(r / "manifest.json").write_text(json.dumps({
    "source": "jordan", "provider": "JACC Jordan", "country": "JO",
    "source_url": "https://www.example.com/jordan", "source_type": "unknown",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
}, indent=2) + "\n")
