#!/usr/bin/env python3
"""Nepal AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "nepal"
r.mkdir(parents=True, exist_ok=True)
print("Nepal AIP: https://e-aip.caanepal.gov.np/")
(r / "manifest.json").write_text(json.dumps({
    "source": "nepal", "country": "NE", "source_url": "https://e-aip.caanepal.gov.np/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
