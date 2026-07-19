#!/usr/bin/env python3
"""Cambodia AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "cambodia"
r.mkdir(parents=True, exist_ok=True)
print("Cambodia AIP: https://aim.cats.com.kh/eaip.html")
(r / "manifest.json").write_text(json.dumps({
    "source": "cambodia", "country": "KH", "source_url": "https://aim.cats.com.kh/eaip.html",
    "source_type": "eaip_html_private_login", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "access_status": "registered_email_verified_login_success",
    "current_private_raw": "data/raw/cambodia/2026-07-09-AIRAC/",
    "notes": [
        "AIS portal requires registration and email verification.",
        "2026-07-09 AIRAC key ENR/AD HTML pages were captured with an authenticated Chrome session.",
        "This stub records status only; re-download requires an authenticated browser/session-aware downloader.",
    ],
}, indent=2) + "\n")
