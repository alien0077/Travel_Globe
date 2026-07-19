#!/usr/bin/env python3
"""UAE AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "uae"
r.mkdir(parents=True, exist_ok=True)
print("UAE AIP: https://www.gcaa.gov.ae/en/ais/Pages/default.aspx")
(r / "manifest.json").write_text(json.dumps({
    "source": "uae", "country": "UA", "source_url": "https://www.gcaa.gov.ae/en/ais/Pages/default.aspx",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
