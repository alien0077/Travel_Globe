#!/usr/bin/env python3
"""Mexico AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "mexico"
r.mkdir(parents=True, exist_ok=True)
print("Mexico AIP: https://www.seneam.gob.mx/AIPMEXICO/aip")
(r / "manifest.json").write_text(json.dumps({
    "source": "mexico", "country": "ME", "source_url": "https://www.seneam.gob.mx/AIPMEXICO/aip",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
