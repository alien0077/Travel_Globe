#!/usr/bin/env python3
"""Brazil AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "brazil"
r.mkdir(parents=True, exist_ok=True)
print("Brazil AIP: https://aisweb.decea.gov.br/")
(r / "manifest.json").write_text(json.dumps({
    "source": "brazil", "country": "BR", "source_url": "https://aisweb.decea.gov.br/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
