#!/usr/bin/env python3
"""Dominican Republic AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "dominicanrep"
r.mkdir(parents=True, exist_ok=True)
print("Dominican Republic AIP: https://aip.sna.gob.do/")
(r / "manifest.json").write_text(json.dumps({
    "source": "dominicanrep", "country": "DO", "source_url": "https://aip.sna.gob.do/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
