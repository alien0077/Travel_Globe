#!/usr/bin/env python3
"""Hungary AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "hungary"
r.mkdir(parents=True, exist_ok=True)
print("Hungary AIP: https://ais-en.hungarocontrol.hu/aip/")
(r / "manifest.json").write_text(json.dumps({
    "source": "hungary", "country": "HU", "source_url": "https://ais-en.hungarocontrol.hu/aip/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
