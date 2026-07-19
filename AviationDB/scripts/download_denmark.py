#!/usr/bin/env python3
"""Denmark AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "denmark"
r.mkdir(parents=True, exist_ok=True)
print("Denmark AIP: https://aim.naviair.dk/")
(r / "manifest.json").write_text(json.dumps({
    "source": "denmark", "country": "DE", "source_url": "https://aim.naviair.dk/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
