#!/usr/bin/env python3
"""Myanmar AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "myanmar"
r.mkdir(parents=True, exist_ok=True)
print("Myanmar AIP: http://www.ais.gov.mm/")
(r / "manifest.json").write_text(json.dumps({
    "source": "myanmar", "country": "MY", "source_url": "http://www.ais.gov.mm/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
