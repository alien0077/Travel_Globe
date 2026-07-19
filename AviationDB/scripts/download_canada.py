#!/usr/bin/env python3
"""加拿大 AIP 下載腳本。NAV CANADA 提供 AIP Canada PDF。
URL: https://www.navcanada.ca/en/aeronautical-information/aip-canada.aspx"""
from __future__ import annotations; import json; from datetime import UTC, datetime; from pathlib import Path
p=Path(__file__).resolve().parent.parent;r=p/"data"/"raw"/"canada";r.mkdir(parents=True,exist_ok=True)
print("加拿大 AIP: https://www.navcanada.ca/en/aeronautical-information/aip-canada.aspx")
print("AIP Canada 為 PDF 格式，可公開下載")
(r/"manifest.json").write_text(json.dumps({"source":"canada","provider":"NAV CANADA","country":"CA",
"source_type":"aip_pdf","source_url":"https://www.navcanada.ca/en/aeronautical-information/aip-canada.aspx",
"retrieved_at":datetime.now(UTC).isoformat(),"redistribution_status":"manual_review_required",
"notes":["AIP 為 PDF 格式"]},indent=2)+"\n")
