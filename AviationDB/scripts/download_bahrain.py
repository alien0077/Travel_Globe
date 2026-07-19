#!/usr/bin/env python3
"""(BH) MTT Bahrain AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "bahrain"
r.mkdir(parents=True, exist_ok=True)
print("BH AIP: https://aim.mtt.gov.bh/eaip")
(r / "manifest.json").write_text(json.dumps({
    "source": "bahrain", "provider": "MTT Bahrain", "country": "BH",
    "source_url": "https://aim.mtt.gov.bh/eaip", "source_type": "unknown",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
}, indent=2) + "\n")
