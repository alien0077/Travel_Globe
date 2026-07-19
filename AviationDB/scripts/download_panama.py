#!/usr/bin/env python3
"""Panama AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "panama"
r.mkdir(parents=True, exist_ok=True)
print("Panama AIP: https://www.aeronautica.gob.pa/ais-aip/")
(r / "manifest.json").write_text(json.dumps({
    "source": "panama", "country": "PA", "source_url": "https://www.aeronautica.gob.pa/ais-aip/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
