#!/usr/bin/env python3
"""Papua New Guinea AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "papuanewguinea"
r.mkdir(parents=True, exist_ok=True)
print("Papua New Guinea AIP: https://www.niuskypacific.com.pg/home/ais-publications/aip/")
(r / "manifest.json").write_text(json.dumps({
    "source": "papuanewguinea", "country": "PA", "source_url": "https://www.niuskypacific.com.pg/home/ais-publications/aip/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
