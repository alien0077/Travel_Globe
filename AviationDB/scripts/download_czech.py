#!/usr/bin/env python3
"""Czech AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "czech"
r.mkdir(parents=True, exist_ok=True)
print("Czech AIP: http://ais.ans.cz/")
(r / "manifest.json").write_text(json.dumps({
    "source": "czech", "country": "CZ", "source_url": "http://ais.ans.cz/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
