#!/usr/bin/env python3
"""Cuba AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "cuba"
r.mkdir(parents=True, exist_ok=True)
print("Cuba AIP: https://aismet.avianet.cu/html/aip.html")
(r / "manifest.json").write_text(json.dumps({
    "source": "cuba", "country": "CU", "source_url": "https://aismet.avianet.cu/html/aip.html",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
