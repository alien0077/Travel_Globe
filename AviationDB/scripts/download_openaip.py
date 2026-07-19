#!/usr/bin/env python3
"""Download OpenAIP navaid and reporting point coordinates for European countries."""
import json, os, sys, time
from pathlib import Path
import requests

API_KEY = os.environ.get("OPENAIP_API_KEY", "")
if not API_KEY:
    print("Error: OPENAIP_API_KEY environment variable not set")
    print("Source ~/.zshrc or export it")
    sys.exit(1)
BASE = "https://api.core.openaip.net/api"
HEADERS = {"x-openaip-api-key": API_KEY}

# Countries needing EAD coordinate fills
COUNTRIES = ["BE", "DE", "NL", "AT", "IT", "SE", "NO", "LT", "SK", "MT", "CH", "TR", "DK", "FI", "IE", "PT", "ES", "FR", "GB", "GR", "PL", "CZ", "HU", "RO", "BG", "HR", "SI", "EE", "LV", "LU", "CY", "IS"]

TYPE_NAMES = {
    1: "OTHER", 2: "ADF", 3: "DME", 4: "GS", 5: "ILS", 6: "ILS_DME",
    7: "VOR", 8: "VOR_DME", 9: "NDB", 10: "TACAN", 11: "VORTAC",
    12: "MARKER", 13: "LOCALIZER", 14: "RADAR", 15: "OMEGA",
    16: "DECCA", 17: "LORAN", 18: "MLS", 19: "SCOPE",
    20: "UNKNOWN", 21: "DME_NAV", 22: "DME_ILS", 23: "POINT",
    24: "WAYPOINT", 25: "REPORTING_POINT"
}

def fetch_all(endpoint: str, params: dict) -> list[dict]:
    """Fetch all pages of an OpenAIP API endpoint."""
    all_items = []
    page = 1
    while True:
        params["page"] = page
        try:
            resp = requests.get(f"{BASE}/{endpoint}", headers=HEADERS, params=params, timeout=30)
            if resp.status_code != 200:
                print(f"  Error {resp.status_code}: {resp.text[:200]}")
                break
            data = resp.json()
            items = data.get("items", data.get("data", []))
            if not items:
                break
            all_items.extend(items)
            total = data.get("totalCount", data.get("total", 0))
            print(f"  Page {page}: {len(items)} items (total: {total})")
            if len(all_items) >= total:
                break
            page += 1
            time.sleep(0.3)  # Rate limiting
        except Exception as e:
            print(f"  Error on page {page}: {e}")
            break
    return all_items

def main():
    out_dir = Path("data/raw/openaip")
    out_dir.mkdir(parents=True, exist_ok=True)
    all_points = {}
    country_stats = {}

    for country in COUNTRIES:
        print(f"\n=== {country} ===")
        
        # Fetch navaids
        navaids = fetch_all("navaids", {"country": country, "limit": 100})
        for nav in navaids:
            ident = nav.get("identifier", "").strip().upper()
            if not ident:
                continue
            coords = nav.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            lat, lon = coords[1], coords[0]
            nav_type = nav.get("type", 0)
            type_name = TYPE_NAMES.get(nav_type, f"TYPE_{nav_type}")
            if ident not in all_points:
                all_points[ident] = (lat, lon, type_name)
        
        # Fetch reporting points
        rpts = fetch_all("reporting-points", {"country": country, "limit": 100})
        for rp in rpts:
            ident = rp.get("name", "").strip().upper()
            if not ident:
                continue
            coords = rp.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            lat, lon = coords[1], coords[0]
            if ident not in all_points:
                all_points[ident] = (lat, lon, "REPORTING_POINT")
        
        country_stats[country] = {"navaids": len(navaids), "rpts": len(rpts)}
        print(f"  => {len(navaids)} navaids, {len(rpts)} rpts")

    # Save all points
    out_file = out_dir / "european_coordinates.json"
    with open(out_file, "w") as f:
        json.dump({
            "source": "openaip",
            "countries": country_stats,
            "total_points": len(all_points),
            "points": {ident: {"lat": lat, "lon": lon, "type": pt} for ident, (lat, lon, pt) in all_points.items()}
        }, f, indent=2)
    
    print(f"\n{'='*50}")
    print(f"Total unique points: {len(all_points)}")
    print(f"Saved to: {out_file}")

if __name__ == "__main__":
    main()
