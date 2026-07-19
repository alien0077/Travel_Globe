#!/usr/bin/env python3
"""Portugal AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "portugal"
r.mkdir(parents=True, exist_ok=True)
print("Portugal AIP: https://ais.nav.pt/")
(r / "manifest.json").write_text(json.dumps({
    "source": "portugal", "country": "PO", "source_url": "https://ais.nav.pt/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
