#!/usr/bin/env python3
"""寮國 AIP 下載腳本。需調查官方來源（可能需註冊）。"""
from __future__ import annotations; import json; from datetime import UTC, datetime; from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent; RAW_DIR = PROJECT_ROOT / "data" / "raw" / "laos"
print("⚠️ 寮國 AIP 來源待調查。寮國 AIP 由 Laos CAA 發布，公開取得狀況不明。")
print("可能來源：EUROCONTROL EAD（需註冊）或直接聯絡 CAA Laos")
RAW_DIR.mkdir(parents=True, exist_ok=True)
(RAW_DIR / "manifest.json").write_text(json.dumps({
    "source":"laos","provider":"Lao CAA","country":"LA","source_type":"unknown",
    "source_url":"","retrieved_at":datetime.now(UTC).isoformat(),
    "redistribution_status":"manual_review_required",
    "notes":["AIP 公開來源待調查"],},indent=2)+"\n")
