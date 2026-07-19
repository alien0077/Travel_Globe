#!/usr/bin/env python3
"""Costa Rica / Central America AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "costarica"
r.mkdir(parents=True, exist_ok=True)
print("Costa Rica / Central America AIP: https://www.cocesna.org/aipca/history.html")
(r / "manifest.json").write_text(json.dumps({
    "source": "costarica", "country": "CO", "source_url": "https://www.cocesna.org/aipca/history.html",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
