#!/usr/bin/env python3
"""
Vietnam eAIP 下載腳本

下載越南 CAAV (Civil Aviation Authority of Viet Nam) 官方 eAIP 文件。
VNAIC 入口：https://vnaic.vn/（需註冊），但 eAIP HTML 檔案可透過 aim.vatm.vn 直接存取。

下載目標：
  - ENR 3.1 Conventional Navigation Routes
  - ENR 3.2 Area Navigation (RNAV) Routes
  - ENR 4.1 Radio Navigation Aids
  - ENR 4.4 Name-Code Designators for Significant Points

用法：
  python scripts/download_vietnam.py                    # 自動下載最新版本
  python scripts/download_vietnam.py --cycle 2026-06-30 # 指定 AIRAC cycle
  python scripts/download_vietnam.py --dry-run          # 僅顯示即將下載的 URL
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
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "vietnam"
BASE_URL = "https://aim.vatm.vn/images/stories/vnaic.vn/SanPhamDichVu/AIPVietNam/AIP"
HISTORY_URL = f"{BASE_URL}/history-en-GB.html"
TIMEOUT = 45

DOCUMENTS = {
    "enr_3_1": {"filename": "VV-ENR-3.1-en-GB.html", "section": "ENR 3.1 - Conventional Navigation Routes"},
    "enr_3_2": {"filename": "VV-ENR-3.2-en-GB.html", "section": "ENR 3.2 - Area Navigation (RNAV) Routes"},
    "enr_4_1": {"filename": "VV-ENR-4.1-en-GB.html", "section": "ENR 4.1 - Radio Navigation Aids"},
    "enr_4_4": {"filename": "VV-ENR-4.4-en-GB.html", "section": "ENR 4.4 - Name-Code Designators"},
}


class _AnchorExtractor(HTMLParser):
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


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def probe_latest_cycle() -> str | None:
    """從 history 頁面探測目前有效 cycle。"""
    try:
        html = _fetch_text(HISTORY_URL)
        # 找 Currently Effective Issue 中的第一個連結
        in_current = False
        for line in html.split("\n"):
            if "Currently Effective" in line:
                in_current = True
            if in_current and 'href="' in line:
                m = re.search(r'href="([^"]+)"', line)
                if m:
                    path = m.group(1)
                    # path 格式: "2026-06-30/html/index-en-GB.html"
                    cycle = path.split("/")[0]
                    return cycle
    except Exception as e:
        print(f"  無法探測 cycle: {e}")
    return None


def download_documents(cycle: str, dry_run: bool = False) -> list[dict[str, Any]]:
    """下載指定 cycle 的 eAIP 文件。"""
    base_url = f"{BASE_URL}/{cycle}/html/eAIP/"
    artifacts: list[dict[str, Any]] = []

    for doc_id, doc_info in DOCUMENTS.items():
        url = urllib.parse.urljoin(base_url, doc_info["filename"])
        target = RAW_DIR / cycle / doc_info["filename"]
        artifact: dict[str, Any] = {
            "id": doc_id,
            "url": url,
            "section": doc_info["section"],
            "target": str(target.relative_to(PROJECT_ROOT)),
        }

        if dry_run:
            print(f"  [{doc_id}] {url}")
            artifact.update({"status": "dry_run"})
            artifacts.append(artifact)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = _fetch_bytes(url)
            target.write_bytes(data)
            artifact.update({"status": "downloaded", "size_bytes": len(data), "sha256": _sha256(data)})
            print(f"  ✓ {doc_id}: {len(data)} bytes")
        except (HTTPError, URLError) as e:
            code = getattr(e, "code", None) if isinstance(e, HTTPError) else None
            artifact.update({"status": "failed", "http_code": code, "error": str(e)})
            print(f"  ✗ {doc_id}: HTTP {code}")
        except Exception as e:
            artifact.update({"status": "failed", "error": str(e)})
            print(f"  ✗ {doc_id}: {e}")

        artifacts.append(artifact)

    return artifacts


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="下載越南 CAAV eAIP 文件")
    parser.add_argument("--cycle", default=None, help="指定 AIRAC cycle (YYYY-MM-DD)，預設自動探測最新版")
    parser.add_argument("--dry-run", action="store_true", help="僅列出 URL，不下載")
    args = parser.parse_args()

    cycle = args.cycle
    if not cycle:
        print("探測目前有效 AIRAC cycle...")
        cycle = probe_latest_cycle()
        if not cycle:
            cycle = "2026-06-30"
            print(f"  無法探測，使用預設: {cycle}")
        else:
            print(f"  偵測到 cycle: {cycle}")

    print(f"\nVietnam eAIP ({cycle})")
    print(f"  {'[DRY RUN]' if args.dry_run else '下載中...'}")
    print()

    artifacts = download_documents(cycle, dry_run=args.dry_run)

    if args.dry_run:
        print(f"\n共 {len(artifacts)} 個文件")
        return

    # 寫入 manifest
    successful = [a for a in artifacts if a.get("status") == "downloaded"]
    manifest: dict[str, Any] = {
        "source": "vietnam",
        "provider": "Civil Aviation Authority of Viet Nam (CAAV) / VNAIC",
        "country": "VN",
        "source_type": "eaip_xhtml",
        "cycle": cycle,
        "retrieved_at": _now(),
        "effective_date": cycle,
        "redistribution_status": "manual_review_required",
        "artifacts": artifacts,
        "summary": {"total": len(artifacts), "downloaded": len(successful), "failed": len(artifacts) - len(successful)},
    }

    manifest_path = RAW_DIR / cycle / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"  manifest: {manifest_path}")

    print()
    print(f"  結果: {len(successful)}/{len(artifacts)} 成功")
    if len(successful) == len(artifacts):
        print(f"  ✓ 全部下載成功！")
        print(f"  下一步: python scripts/parse_vietnam.py --dir data/raw/vietnam/{cycle}")
    else:
        print(f"  ⚠️ 部分失敗")
        sys.exit(1)


if __name__ == "__main__":
    main()
