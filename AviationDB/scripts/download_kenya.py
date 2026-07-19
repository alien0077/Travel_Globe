#!/usr/bin/env python3
"""Kenya AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "kenya"
r.mkdir(parents=True, exist_ok=True)
print("Kenya AIP: http://eaip.kcaa.or.ke/")
(r / "manifest.json").write_text(json.dumps({
    "source": "kenya", "country": "KE", "source_url": "http://eaip.kcaa.or.ke/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
