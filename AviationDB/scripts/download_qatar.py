#!/usr/bin/env python3
"""QA - QCAA AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path

p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "qatar"
r.mkdir(parents=True, exist_ok=True)

print("QA AIP: https://www.caa.gov.qa/")
print("Access may require registration. Check the URL above.")

(r / "manifest.json").write_text(json.dumps({
    "source": "qatar",
    "provider": "QCAA",
    "country": "QA",
    "source_url": "https://www.caa.gov.qa/",
    "source_type": "unknown",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIP access status needs confirmation"],
}, indent=2) + "\n")
