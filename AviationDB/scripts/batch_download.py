#!/usr/bin/env python3
"""AviationDB 批次下載 — 一次下載所有可存取的 eAIP。"""
from __future__ import annotations
import hashlib, json, re, time, urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
TIMEOUT = 30

# 各國設定: (ICAO, country, FIR, region, host, cycle探测方式, files)
COUNTRIES = {
    "portugal": {
        "cc":"PT","fir":"LISBOA","region":"europe",
        "host":"https://ais.nav.pt/wp-content/uploads/AIS_Files/eAIP_Current/eAIP_Online/eAIP/html/eAIP",
        "direct":True,
        "files":{"enr_3_1":"LP-ENR-3.1-en-PT.html","enr_3_3":"LP-ENR-3.3-en-PT.html","enr_4_4":"LP-ENR-4.4-en-PT.html"},
    },
    "vietnam": {
        "cc":"VN","fir":"HO_CHI_MINH","region":"asia-southeast",
        "host":"https://aim.vatm.vn/images/stories/vnaic.vn/SanPhamDichVu/AIPVietNam/AIP",
        "probe_url":"https://aim.vatm.vn/images/stories/vnaic.vn/SanPhamDichVu/AIPVietNam/AIP/history-en-GB.html",
        "cycle_re":r'href="([^/]+)/html/index-en-GB\.html"',
        "url_tpl":"{host}/{cycle}/html/eAIP/{file}",
        "files":{"enr_3_1":"VV-ENR-3.1-en-GB.html","enr_3_2":"VV-ENR-3.2-en-GB.html","enr_4_4":"VV-ENR-4.4-en-GB.html"},
    },
    "bahrain": {
        "cc":"BH","fir":"BAHRAIN","region":"middle-east",
        "host":"https://aim.mtt.gov.bh/eAIP",
        "probe_url":"https://aim.mtt.gov.bh/eaip",
        "cycle_re":r'href="([^/]+)/html/index-en-BH\.html"',
        "url_tpl":"{host}/{cycle}/html/eAIP/{file}",
        "files":{"enr_3_1":"OB-ENR-3.1-en-BH.html","enr_3_3":"OB-ENR-3.3-en-BH.html","enr_4_4":"OB-ENR-4.4-en-BH.html"},
    },
    "israel": {
        "cc":"IL","fir":"TEL_AVIV","region":"middle-east",
        "host":"https://e-aip.azurefd.net",
        "probe_url":"https://e-aip.azurefd.net/",
        "cycle_re":r'href="([^"]+)/html/index\.html"',
        "url_tpl":"{host}/{cycle}/html/eAIP/{file}",
        "files":{"enr_3_1":"LL-ENR-3.1-en-GB.html","enr_3_3":"LL-ENR-3.3-en-GB.html","enr_4_4":"LL-ENR-4.4-en-GB.html"},
    },
    "qatar": {
        "cc":"QA","fir":"DOHA","region":"middle-east",
        "host":"https://www.aim.gov.qa/eaip",
        "probe_url":"https://www.caa.gov.qa/en/aeronautical-information-management",
        "cycle_re":r'href="https://www\.aim\.gov\.qa/eaip/([^/]+)/html/index-en-GB\.html"',
        "url_tpl":"{host}/{cycle}/html/eAIP/{file}",
        "files":{"enr_3_1":"ENR-3.1-en-GB.html","enr_3_2":"ENR-3.2-en-GB.html","enr_4_4":"ENR-4.4-en-GB.html"},
    },
    "jordan": {
        "cc":"JO","fir":"AMMAN","region":"middle-east",
        "host":"https://www.jacc.gov.jo/eAIP",
        "probe_url":"https://www.jacc.gov.jo/",
        "cycle_re":r'href="([^"]+)/html/index-en-JO\.html"',
        "url_tpl":"{host}/{cycle}/html/eAIP/{file}",
        "files":{"enr_3_1":"OJ-ENR-3.1-en-JO.html","enr_4_4":"OJ-ENR-4.4-en-JO.html"},
    },
    "italy": {
        "cc":"IT","fir":"ROMA","region":"europe",
        "host":"https://www.enav.it/eAIP",
        "probe_url":"https://www.enav.it/",
        "cycle_re":r'href="([^"]+)/html/index-en-IT\.html"',
        "url_tpl":"{host}/{cycle}/html/eAIP/{file}",
        "files":{"enr_3_1":"LI-ENR-3.1-en-IT.html","enr_4_4":"LI-ENR-4.4-en-IT.html"},
    },
    "spain": {
        "cc":"ES","fir":"MADRID","region":"europe",
        "host":"https://eaip.enaire.es/eAIP",
        "probe_url":"https://eaip.enaire.es/",
        "cycle_re":r'href="([^"]+)/html/index-en-ES\.html"',
        "url_tpl":"{host}/{cycle}/html/eAIP/{file}",
        "files":{"enr_3_1":"LE-ENR-3.1-en-ES.html","enr_4_4":"LE-ENR-4.4-en-ES.html"},
    },
    "france": {
        "cc":"FR","fir":"PARIS","region":"europe",
        "host":"https://www.sia.aviation-civile.gouv.fr/eAIP",
        "probe_url":"https://www.sia.aviation-civile.gouv.fr/",
        "cycle_re":r'href="([^"]+)/html/index-en-FR\.html"',
        "url_tpl":"{host}/{cycle}/html/eAIP/{file}",
        "files":{"enr_3_1":"LF-ENR-3.1-en-FR.html","enr_4_4":"LF-ENR-4.4-en-FR.html"},
    },
    "brazil": {
        "cc":"BR","fir":"BRASILIA","region":"south-america",
        "host":"https://aisweb.decea.mil.br/eaip",
        "probe_url":"https://aisweb.decea.mil.br/eaip",
        "cycle_re":r'href="([^"]+)/eAIP/ENR[^"]*"',
        "url_tpl":"{host}/{cycle}/eAIP/{file}",
        "files":{"enr_3_1":"ENR%203.1-en-GB.html","enr_4_4":"ENR%204.4-en-GB.html"},
    },
}

def _fetch(url: str) -> bytes | None:
    for _ in range(2):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except Exception:
            time.sleep(2)
    return None

def probe_cycle(cfg: dict) -> str | None:
    url = cfg.get("probe_url")
    pat = cfg.get("cycle_re", r'href="([^"]+)"')
    if not url:
        return None
    html = _fetch(url)
    if not html:
        return None
    for m in re.finditer(pat, html.decode()):
        cycle = m.group(1).split("/")[0]
        if cycle and not cycle.startswith("http"):
            return cycle
    return None

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    
    targets = args.countries.split(",") if args.countries else list(COUNTRIES.keys())
    
    print(f"批次下載: {len(targets)} 國\n")
    total_ok = 0
    
    for cid in targets:
        if cid not in COUNTRIES:
            print(f"  ⚠ 未知: {cid}")
            continue
        cfg = COUNTRIES[cid]
        raw_dir = RAW / cid
        raw_dir.mkdir(parents=True, exist_ok=True)
        cc = cfg["cc"]
        
        print(f"[{cc}] {cid}...")
        
        # Probe cycle
        if cfg.get("direct"):
            cycle = None
        else:
            cycle = probe_cycle(cfg)
            if not cycle:
                print(f"  ✗ 無法探測 cycle")
                continue
            print(f"  cycle: {cycle}")
        
        arts = []
        for did, fn in cfg["files"].items():
            if cfg.get("direct"):
                url = f"{cfg['host']}/{fn}"
            else:
                url = cfg["url_tpl"].format(host=cfg["host"], cycle=cycle, file=fn)
            
            if args.dry_run:
                print(f"  [{did}] {url}")
                arts.append({"id": did, "status": "dry_run"})
                continue
            
            data = _fetch(url)
            if data is None:
                print(f"  ✗ {did}: failed")
                arts.append({"id": did, "status": "failed"})
                continue
            
            (raw_dir / fn).write_bytes(data)
            sha = hashlib.sha256(data).hexdigest()
            arts.append({"id": did, "status": "downloaded", "bytes": len(data), "sha256": sha})
            print(f"  ✓ {did}: {len(data)} bytes")
            total_ok += 1
        
        (raw_dir / "manifest.json").write_text(json.dumps({
            "source": cid, "country": cc, "source_type": "eaip_html",
            "artifacts": arts,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "redistribution_status": "manual_review_required",
        }, indent=2) + "\n")
    
    print(f"\n總計: {total_ok} 檔案下載成功")

if __name__ == "__main__":
    main()
