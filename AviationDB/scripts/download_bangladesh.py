#!/usr/bin/env python3
"""Bangladesh AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "bangladesh"
r.mkdir(parents=True, exist_ok=True)
print("Bangladesh AIP: http://new.caab.gov.bd/aip/")
(r / "manifest.json").write_text(json.dumps({
    "source": "bangladesh", "country": "BA", "source_url": "http://new.caab.gov.bd/aip/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
