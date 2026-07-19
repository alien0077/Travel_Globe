#!/usr/bin/env python3
"""Record Peru CORPAC AIP access status."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "peru"
r.mkdir(parents=True, exist_ok=True)
source_url = "https://www.gob.pe/institucion/corpac/pages/31713-acceder-a-la-publicacion-de-informacion-aeronautica-de-corpac"
print(f"PE AIP: {source_url}")
(r / "manifest.json").write_text(json.dumps({
    "source": "peru", "provider": "CORPAC Peru", "country": "PE",
    "source_url": source_url, "source_type": "paid_account_portal",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "status": "blocked_paid_account_access",
    "notes": [
        "Official gob.pe service page states AIP Digital requires username/password.",
        "Credential path requires coordinating payment with AIS Peru by phone/email; do not auto-pay.",
    ],
}, indent=2) + "\n")
