#!/usr/bin/env python3
"""Indonesia AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "indonesia"
r.mkdir(parents=True, exist_ok=True)
print("Indonesia AIP: https://aimindonesia.dephub.go.id/")
(r / "manifest.json").write_text(json.dumps({
    "source": "indonesia", "country": "ID", "source_url": "https://aimindonesia.dephub.go.id/",
    "source_type": "eaip_endpoint_unresolved", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "access_status": "blocked_dns_unresolved_or_current_endpoint_unknown",
    "notes": [
        "The known hostname did not resolve during the 2026-07-18 probe.",
        "Search results did not reveal a reliable current official AIM/eAIP registration endpoint.",
    ],
}, indent=2) + "\n")
