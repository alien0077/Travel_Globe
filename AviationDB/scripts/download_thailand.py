#!/usr/bin/env python3
"""
Thailand eAIP 下載腳本

下載泰國 CAAT (Civil Aviation Authority of Thailand) 官方 eAIP 文件。
需要先同意 ais.caat.or.th 的條款，但 aip.caat.or.th 子域有 Cloudflare WAF 保護，
自動化下載可能被阻擋。

下載目標：
  - ENR 3.1 Lower and Upper ATS Routes
  - ENR 3.3 Area Navigation (RNAV) Routes
  - ENR 3.5 Other Routes
  - ENR 4.1 Radio Navigation Aids
  - ENR 4.4 Name-Code Designators for Significant Points

用法：
  python scripts/download_thailand.py                    # 嘗試自動下載
  python scripts/download_thailand.py --manual            # 僅輸出手動下載說明
  python scripts/download_thailand.py --cycle 2026-07-09  # 指定 AIRAC cycle
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "thailand"
TIMEOUT = 45

# 已知的 eAIP URL 模式
# 基礎 URL: https://aip.caat.or.th/{AIRAC_CYCLE}-AIRAC/html/eAIP/{FILENAME}
DOCUMENTS = {
    "enr_3_1": {"filename": "VT-ENR-3.1-en-GB.html", "section": "ENR 3.1 - Lower and Upper ATS Routes"},
    "enr_3_3": {"filename": "VT-ENR-3.3-en-GB.html", "section": "ENR 3.3 - Area Navigation (RNAV) Routes"},
    "enr_3_5": {"filename": "VT-ENR-3.5-en-GB.html", "section": "ENR 3.5 - Other Routes"},
    "enr_4_1": {"filename": "VT-ENR-4.1-en-GB.html", "section": "ENR 4.1 - Radio Navigation Aids"},
    "enr_4_4": {"filename": "VT-ENR-4.4-en-GB.html", "section": "ENR 4.4 - Name-Code Designators"},
}


class _AnchorExtractor(HTMLParser):
    """Extract <a> links from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self._href = next((v for k, v in attrs if k.lower() == "href"), None)
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, " ".join(self._text).strip()))
        self._href = None
        self._text = []


def _fetch_text(url: str, opener: urllib.request.OpenerDirector | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = opener or urllib.request.build_opener()
    with opener.open(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_bytes(url: str, opener: urllib.request.OpenerDirector | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = opener or urllib.request.build_opener()
    with opener.open(req, timeout=TIMEOUT) as resp:
        return resp.read()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def probe_current_cycle() -> str | None:
    """從 published eAIPs 頁面探測目前有效 AIRAC cycle。"""
    try:
        html = _fetch_text("https://aip.caat.or.th/")
        # 尋找 "Currently Effective Issue" 表格中的日期
        for m in re.finditer(r"(\d{1,2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{4})", html):
            date_str = m.group(1)
            # 轉換為 YYYY-MM-DD 格式
            month_map = {
                "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
                "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
                "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
            }
            parts = date_str.split()
            if len(parts) == 3:
                day = parts[0].zfill(2)
                month = month_map.get(parts[1].upper(), "00")
                year = parts[2]
                return f"{year}-{month}-{day}"
    except Exception as e:
        print(f"  無法探測 cycle (aip.caat.or.th 可能被 WAF 阻擋): {e}")
    return None


def attempt_agreement_flow() -> urllib.request.OpenerDirector | None:
    """嘗試通過 ais.caat.or.th 的條款同意流程。"""
    import http.cookiejar

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    try:
        html = _fetch_text("https://ais.caat.or.th/", opener)
        token_match = re.search(r'name="_token".*?value="([^"]+)"', html)
        if not token_match:
            print("  ✗ 無法找到 CSRF token")
            return None

        token = token_match.group(1)
        data = urllib.parse.urlencode({"_token": token, "agree": "on"}).encode()
        req = urllib.request.Request(
            "https://ais.caat.or.th/setLanding",
            data=data,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://ais.caat.or.th/",
            },
        )
        with opener.open(req, timeout=TIMEOUT) as resp:
            if resp.status == 200:
                print("  ✓ 條款同意成功")
                return opener
    except Exception as e:
        print(f"  ✗ 條款同意流程失敗: {e}")
    return None


def try_download_via_aip_direct(cycle: str, opener: urllib.request.OpenerDirector | None) -> list[dict[str, Any]]:
    """直接嘗試從 aip.caat.or.th 下載（可能被 WAF 阻擋）。"""
    artifacts: list[dict[str, Any]] = []
    base_url = f"https://aip.caat.or.th/{cycle}-AIRAC/html/eAIP/"

    for doc_id, doc_info in DOCUMENTS.items():
        url = urllib.parse.urljoin(base_url, doc_info["filename"])
        target = RAW_DIR / cycle / doc_info["filename"]
        target.parent.mkdir(parents=True, exist_ok=True)

        artifact: dict[str, Any] = {
            "id": doc_id,
            "url": url,
            "section": doc_info["section"],
            "target": str(target.relative_to(PROJECT_ROOT)),
        }

        try:
            fetcher = opener if opener else urllib.request.build_opener()
            data = _fetch_bytes(url, fetcher)
            target.write_bytes(data)
            artifact.update({"status": "downloaded", "size_bytes": len(data), "sha256": _sha256(data)})
            print(f"  ✓ {doc_id}: {len(data)} bytes 已下載")
        except (HTTPError, URLError) as e:
            code = getattr(e, "code", None) if isinstance(e, HTTPError) else None
            artifact.update({"status": "blocked", "http_code": code, "error": str(e)})
            print(f"  ✗ {doc_id}: HTTP {code} - WAF 阻擋")
        except Exception as e:
            artifact.update({"status": "failed", "error": str(e)})
            print(f"  ✗ {doc_id}: {e}")

        artifacts.append(artifact)

    return artifacts


def print_manual_instructions(cycle: str) -> None:
    """輸出手動下載說明。"""
    base_url = f"https://aip.caat.or.th/{cycle}-AIRAC/html/eAIP/"
    print("\n" + "=" * 70)
    print("  手動下載步驟")
    print("=" * 70)
    print(f"\n目前有效 AIRAC cycle: {cycle}")
    print(f"eAIP 基礎 URL: {base_url}")
    print()
    print("請在瀏覽器中：")
    print(f"  1. 開啟 https://ais.caat.or.th/")
    print(f"  2. 同意 Terms & Conditions")
    print(f"  3. 點擊 eAIP 連結前往 https://aip.caat.or.th")
    print(f"  4. 瀏覽到目前有效的 AIRAC cycle ({cycle})")
    print()

    for doc_id, doc_info in DOCUMENTS.items():
        url = urllib.parse.urljoin(base_url, doc_info["filename"])
        target = RAW_DIR / cycle / doc_info["filename"]
        print(f"  文件: {doc_info['section']}")
        print(f"    URL: {url}")
        print(f"    另存至: {target}")
        print()

    print(f"下載完成後，執行: python scripts/parse_thailand.py --dir data/raw/thailand/{cycle}")
    print()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="下載泰國 CAAT eAIP 文件")
    parser.add_argument("--manual", action="store_true", help="僅輸出手動下載說明")
    parser.add_argument("--cycle", default=None, help="指定 AIRAC cycle (YYYY-MM-DD)，預設自動探測")
    args = parser.parse_args()

    # 探測或使用指定的 cycle
    cycle = args.cycle
    if not cycle:
        print("探測目前有效 AIRAC cycle...")
        cycle = probe_current_cycle()
        if not cycle:
            # 預設使用已知最新版
            cycle = "2026-07-09"
            print(f"  使用預設 cycle: {cycle}")
        else:
            print(f"  偵測到 cycle: {cycle}")
    else:
        print(f"使用指定 cycle: {cycle}")

    if args.manual:
        print_manual_instructions(cycle)
        return

    print(f"\n嘗試自動下載 Thailand eAIP ({cycle})...")
    print()

    # 步驟 1: 嘗試條款同意流程
    print("[1/3] 嘗試 ais.caat.or.th 條款同意...")
    opener = attempt_agreement_flow()

    # 步驟 2: 嘗試直接下載
    print(f"\n[2/3] 嘗試從 aip.caat.or.th 下載...")
    artifacts = try_download_via_aip_direct(cycle, opener)

    # 步驟 3: 寫入 manifest
    print(f"\n[3/3] 寫入 manifest...")
    successful = [a for a in artifacts if a.get("status") == "downloaded"]
    blocked = [a for a in artifacts if a.get("status") == "blocked"]

    manifest: dict[str, Any] = {
        "source": "thailand",
        "provider": "Civil Aviation Authority of Thailand (CAAT)",
        "country": "TH",
        "source_type": "eaip_xhtml",
        "cycle": cycle,
        "retrieved_at": _now(),
        "effective_date": cycle,
        "redistribution_status": "manual_review_required",
        "artifacts": artifacts,
        "summary": {
            "total": len(artifacts),
            "downloaded": len(successful),
            "blocked": len(blocked),
        },
    }

    manifest_path = RAW_DIR / cycle / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"  manifest: {manifest_path}")

    # 結果摘要
    print()
    print("=" * 70)
    print(f"  結果: {len(successful)} 成功, {len(blocked)} 被阻擋")
    print("=" * 70)

    if blocked:
        print()
        print("⚠️  aip.caat.or.th 有 Cloudflare WAF 保護，自動化下載可能被阻擋。")
        print("   請嘗試手動下載:")
        print_manual_instructions(cycle)
        sys.exit(1)

    print("✓ 所有檔案下載成功！")
    print(f"  執行 parser: python scripts/parse_thailand.py --dir data/raw/thailand/{cycle}")


if __name__ == "__main__":
    main()
