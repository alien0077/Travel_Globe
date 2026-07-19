#!/usr/bin/env python3
"""South Africa AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "southafrica"
r.mkdir(parents=True, exist_ok=True)
print("South Africa AIP: https://atns.com/products-services/aim/aeronautical-information-management/7403/")
(r / "manifest.json").write_text(json.dumps({
    "source": "southafrica", "country": "SO", "source_url": "https://atns.com/products-services/aim/aeronautical-information-management/7403/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
