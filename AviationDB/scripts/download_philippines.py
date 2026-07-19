#!/usr/bin/env python3
"""Philippines AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "philippines"
r.mkdir(parents=True, exist_ok=True)
print("Philippines AIP: https://ais.caap.gov.ph/home")
(r / "manifest.json").write_text(json.dumps({
    "source": "philippines", "country": "PH", "source_url": "https://ais.caap.gov.ph/home",
    "source_type": "subscription_portal", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "access_status": "blocked_paid_or_complimentary_subscription_required",
    "notes": [
        "CAAP registration is limited to paid and complimentary Philippine AIP subscribers.",
        "Registration requires subscription evidence / OR Number; do not auto-register without a valid subscription.",
    ],
}, indent=2) + "\n")
