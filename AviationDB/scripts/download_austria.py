#!/usr/bin/env python3
"""Austria AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "austria"
r.mkdir(parents=True, exist_ok=True)
print("Austria AIP: https://eaip.austrocontrol.at/")
(r / "manifest.json").write_text(json.dumps({
    "source": "austria", "country": "AU", "source_url": "https://eaip.austrocontrol.at/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
