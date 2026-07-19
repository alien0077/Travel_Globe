#!/usr/bin/env python3
"""Spain AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "spain"
r.mkdir(parents=True, exist_ok=True)
print("Spain AIP: https://aip.enaire.es/aip/")
(r / "manifest.json").write_text(json.dumps({
    "source": "spain", "country": "SP", "source_url": "https://aip.enaire.es/aip/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
