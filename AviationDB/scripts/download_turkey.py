#!/usr/bin/env python3
"""Turkey AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "turkey"
r.mkdir(parents=True, exist_ok=True)
print("Turkey AIP: https://www.dhmi.gov.tr/Sayfalar/aipturkey.aspx")
(r / "manifest.json").write_text(json.dumps({
    "source": "turkey", "country": "TU", "source_url": "https://www.dhmi.gov.tr/Sayfalar/aipturkey.aspx",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
