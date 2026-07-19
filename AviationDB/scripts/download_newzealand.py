#!/usr/bin/env python3
"""New Zealand AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "newzealand"
r.mkdir(parents=True, exist_ok=True)
print("New Zealand AIP: http://www.aip.net.nz/")
(r / "manifest.json").write_text(json.dumps({
    "source": "newzealand", "country": "NE", "source_url": "http://www.aip.net.nz/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
