#!/usr/bin/env python3
"""UK AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "uk"
r.mkdir(parents=True, exist_ok=True)
print("UK AIP: https://www.nats.aero/do-it-online/ais/")
(r / "manifest.json").write_text(json.dumps({
    "source": "uk", "country": "UK", "source_url": "https://www.nats.aero/do-it-online/ais/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
