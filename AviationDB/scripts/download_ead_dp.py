#!/usr/bin/env python3
"""下載 EAD Basic Designated Points 報告。

需要先手動從瀏覽器取得 JSESSIONID cookie。
用法：
  python scripts/download_ead_dp.py <jsessionid>
"""
import sys
import requests
import re
from pathlib import Path

BASE = "https://eadbasic.ead-it.com/fwf-eadbasic"
REPORT_URL = f"{BASE}/sdopresentreport"
LOGIN_PAGE = f"{BASE}/public/cms/cmscontent.faces?configKey=default.home.page"
SDO_REPORT = f"{BASE}/restricted/reporting/reporting.faces"

def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/download_ead_dp.py <jsessionid>")
        print("從瀏覽器開發工具 > Application > Cookies 找 JSESSIONID")
        sys.exit(1)

    jsessionid = sys.argv[1]
    sess = requests.Session()
    sess.cookies.set("IBSSessionCookie/fwf-eadbasic", jsessionid, domain=".ead-it.com")
    sess.cookies.set("JSESSIONID", jsessionid, domain=".ead-it.com")
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    })

    # Check if the current report is accessible
    resp = sess.get(REPORT_URL, timeout=15)
    print(f"Report URL: HTTP {resp.status_code}, {len(resp.content)} bytes")
    if resp.status_code == 200 and len(resp.content) > 100:
        out = Path("data/raw/ead/designated-points/designated-points-NE.xml")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(resp.content)
        print(f"已儲存至 {out}")
        print(f"內容前 300 字元:\n{resp.text[:300]}")
    else:
        print(f"內容: {resp.text[:200]}")
        print("\n可能 session 已過期，請重新登入後取得新的 JSESSIONID")

if __name__ == "__main__":
    main()
