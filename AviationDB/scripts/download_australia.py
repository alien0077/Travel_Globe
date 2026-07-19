#!/usr/bin/env python3
"""澳洲 AIP 下載腳本。AIP 可從 Airservices Australia 取得（需同意版權條款）。
URL: https://www.airservicesaustralia.com/aip/aip.asp
目前 AIP 為完整 PDF 格式（含 ENR 章節），非 HTML 格式。"""
from __future__ import annotations; import json; from datetime import UTC, datetime; from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent; RAW_DIR = PROJECT_ROOT / "data" / "raw" / "australia"
print("澳洲 AIP: https://www.airservicesaustralia.com/aip/aip.asp")
print("完整 AIP PDF 可下載（需同意版權），含 ENR 3.1, 3.2, 3.3, 4.4 等章節")
print("檔案格式: PDF（非 HTML），需 PDF text extraction parser")
RAW_DIR.mkdir(parents=True, exist_ok=True)
(RAW_DIR / "manifest.json").write_text(json.dumps({
    "source":"australia","provider":"Airservices Australia","country":"AU","source_type":"aip_pdf",
    "source_url":"https://www.airservicesaustralia.com/aip/aip.asp","retrieved_at":datetime.now(UTC).isoformat(),
    "redistribution_status":"manual_review_required",
    "notes":["AIP 為 PDF 格式，需 parser 支援 PDF text extraction"]},indent=2)+"\n")
