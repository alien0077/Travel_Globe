#!/usr/bin/env python3
"""Poland AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "poland"
r.mkdir(parents=True, exist_ok=True)
print("Poland AIP: https://www.ais.pansa.pl/en/publications/ais-products/")
(r / "manifest.json").write_text(json.dumps({
    "source": "poland", "country": "PO", "source_url": "https://www.ais.pansa.pl/en/publications/ais-products/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
