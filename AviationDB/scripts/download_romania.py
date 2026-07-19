#!/usr/bin/env python3
"""Romania AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "romania"
r.mkdir(parents=True, exist_ok=True)
print("Romania AIP: https://www.aisro.ro/")
(r / "manifest.json").write_text(json.dumps({
    "source": "romania", "country": "RO", "source_url": "https://www.aisro.ro/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
