#!/usr/bin/env python3
"""Sweden AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "sweden"
r.mkdir(parents=True, exist_ok=True)
print("Sweden AIP: https://aro.lfv.se/Editorial/View/IAIP")
(r / "manifest.json").write_text(json.dumps({
    "source": "sweden", "country": "SW", "source_url": "https://aro.lfv.se/Editorial/View/IAIP",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
