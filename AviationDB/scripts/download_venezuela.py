#!/usr/bin/env python3
"""Venezuela AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "venezuela"
r.mkdir(parents=True, exist_ok=True)
print("Venezuela AIP: http://www.inac.gob.ve/eaip/history-en-GB.html")
(r / "manifest.json").write_text(json.dumps({
    "source": "venezuela", "country": "VE", "source_url": "http://www.inac.gob.ve/eaip/history-en-GB.html",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
