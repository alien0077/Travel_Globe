#!/usr/bin/env python3
"""Saudi Arabia AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "saudiarabia"
r.mkdir(parents=True, exist_ok=True)
print("Saudi Arabia AIP: https://www.sans.com.sa/services/services-aim")
(r / "manifest.json").write_text(json.dumps({
    "source": "saudiarabia", "country": "SA", "source_url": "https://www.sans.com.sa/services/services-aim",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
