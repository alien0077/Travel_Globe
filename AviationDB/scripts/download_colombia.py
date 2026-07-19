#!/usr/bin/env python3
"""Record Colombia Aerocivil AIP access status."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path

p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "colombia"
r.mkdir(parents=True, exist_ok=True)

source_url = "https://www.aerocivil.gov.co/servicios-a-la-navegacion/servicio-de-informacion-aeronautica-ais/aip"
print(f"CO AIP: {source_url}")
print("Search-visible AIP page currently redirects to Aerocivil 404 from curl probes.")

(r / "manifest.json").write_text(json.dumps({
    "source": "colombia",
    "provider": "Aerocivil",
    "country": "CO",
    "source_url": source_url,
    "source_type": "aip_pdf_portal",
    "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "status": "blocked_direct_url_404",
    "notes": [
        "Search cache lists AIP PDF AMDT 68/25 WEF 12 JUN 2025 with ENR 3/4 sections.",
        "Direct curl probes to /aip, /generalidades, and the parent AIS path returned Aerocivil 404 pages.",
        "Next step is browser navigation or updated attachment endpoint discovery.",
    ],
}, indent=2) + "\n")
