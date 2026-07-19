#!/usr/bin/env python3
"""Sri Lanka AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "srilanka"
r.mkdir(parents=True, exist_ok=True)
print("Sri Lanka AIP: https://www.aimsrilanka.lk/")
(r / "manifest.json").write_text(json.dumps({
    "source": "srilanka", "country": "SR", "source_url": "https://www.aimsrilanka.lk/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
