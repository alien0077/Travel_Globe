#!/usr/bin/env python3
"""Finland AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "finland"
r.mkdir(parents=True, exist_ok=True)
print("Finland AIP: https://www.ais.fi/")
(r / "manifest.json").write_text(json.dumps({
    "source": "finland", "country": "FI", "source_url": "https://www.ais.fi/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
