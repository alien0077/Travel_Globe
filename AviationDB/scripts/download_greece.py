#!/usr/bin/env python3
"""Greece AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "greece"
r.mkdir(parents=True, exist_ok=True)
print("Greece AIP: https://aisgr.hasp.gov.gr/")
(r / "manifest.json").write_text(json.dumps({
    "source": "greece", "country": "GR", "source_url": "https://aisgr.hasp.gov.gr/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
