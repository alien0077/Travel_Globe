#!/usr/bin/env python3
"""Germany AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "germany"
r.mkdir(parents=True, exist_ok=True)
print("Germany AIP: https://aip.dfs.de/basicAIP/")
(r / "manifest.json").write_text(json.dumps({
    "source": "germany", "country": "GE", "source_url": "https://aip.dfs.de/basicAIP/",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
