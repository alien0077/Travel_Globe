#!/usr/bin/env python3
"""Kuwait AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "kuwait"
r.mkdir(parents=True, exist_ok=True)
print("Kuwait AIP: https://dgca.gov.kw/AIP")
(r / "manifest.json").write_text(json.dumps({
    "source": "kuwait", "country": "KU", "source_url": "https://dgca.gov.kw/AIP",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
