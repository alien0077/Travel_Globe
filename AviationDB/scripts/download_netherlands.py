#!/usr/bin/env python3
"""Netherlands AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "netherlands"
r.mkdir(parents=True, exist_ok=True)
print("Netherlands AIP: https://www.lvnl.nl/diensten/aip")
(r / "manifest.json").write_text(json.dumps({
    "source": "netherlands", "country": "NE", "source_url": "https://www.lvnl.nl/diensten/aip",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
