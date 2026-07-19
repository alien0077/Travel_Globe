#!/usr/bin/env python3
"""Argentina AIP download script."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
p = Path(__file__).resolve().parent.parent
r = p / "data" / "raw" / "argentina"
r.mkdir(parents=True, exist_ok=True)
print("Argentina AIP: https://ais.anac.gob.ar/aip")
(r / "manifest.json").write_text(json.dumps({
    "source": "argentina", "country": "AR", "source_url": "https://ais.anac.gob.ar/aip",
    "source_type": "eaip", "retrieved_at": datetime.now(UTC).isoformat(),
    "redistribution_status": "manual_review_required",
    "notes": ["AIS portal from Eurocontrol AIS Online directory"],
}, indent=2) + "\n")
