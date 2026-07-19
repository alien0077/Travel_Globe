#!/usr/bin/env python3
"""(CH) Skyguide Switzerland AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "switzerland"
r.mkdir(parents=True, exist_ok=True)
print("CH AIP: https://www.skybriefing.com/aip/")
(r / "manifest.json").write_text(json.dumps({
    "source": "switzerland", "provider": "Skyguide Switzerland", "country": "CH",
    "source_url": "https://www.skybriefing.com/aip/", "source_type": "login_portal",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "access_status": "registration_flow_not_found_on_public_register_page",
    "notes": [
        "Skybriefing /aip redirects into a login context.",
        "The /registrieren page showed email verification instructions but no visible registration form in the first probe.",
    ],
}, indent=2) + "\n")
