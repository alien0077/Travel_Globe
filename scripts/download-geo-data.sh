#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
export LANG=C

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$ROOT_DIR/shared/source-data"
MANIFEST="$SOURCE_DIR/source-manifest.tsv"

mkdir -p "$SOURCE_DIR/natural-earth" "$SOURCE_DIR/ourairports" "$SOURCE_DIR/nasa"

download() {
  local url="$1"
  local output="$2"
  echo "Downloading $url"
  curl -fL "$url" -o "$output"
}

download "https://naturalearth.s3.amazonaws.com/110m_cultural/ne_110m_admin_0_countries.zip" \
  "$SOURCE_DIR/natural-earth/ne_110m_admin_0_countries.zip"
download "https://naturalearth.s3.amazonaws.com/110m_cultural/ne_110m_populated_places.zip" \
  "$SOURCE_DIR/natural-earth/ne_110m_populated_places.zip"
download "https://naturalearth.s3.amazonaws.com/110m_physical/ne_110m_land.zip" \
  "$SOURCE_DIR/natural-earth/ne_110m_land.zip"
download "https://naturalearth.s3.amazonaws.com/110m_physical/ne_110m_coastline.zip" \
  "$SOURCE_DIR/natural-earth/ne_110m_coastline.zip"

download "https://davidmegginson.github.io/ourairports-data/airports.csv" \
  "$SOURCE_DIR/ourairports/airports.csv"
download "https://davidmegginson.github.io/ourairports-data/runways.csv" \
  "$SOURCE_DIR/ourairports/runways.csv"
download "https://davidmegginson.github.io/ourairports-data/navaids.csv" \
  "$SOURCE_DIR/ourairports/navaids.csv"
download "https://davidmegginson.github.io/ourairports-data/countries.csv" \
  "$SOURCE_DIR/ourairports/countries.csv"
download "https://davidmegginson.github.io/ourairports-data/regions.csv" \
  "$SOURCE_DIR/ourairports/regions.csv"

download "https://eoimages.gsfc.nasa.gov/images/imagerecords/57000/57730/land_ocean_ice_2048.jpg" \
  "$SOURCE_DIR/nasa/blue-marble-land-ocean-ice-2048.jpg"

{
  printf "sha256\tbytes\tpath\tsource\n"
  find "$SOURCE_DIR" -type f ! -name "$(basename "$MANIFEST")" | sort | while read -r file; do
    sha="$(shasum -a 256 "$file" | awk '{print $1}')"
    bytes="$(wc -c < "$file" | tr -d ' ')"
    relative="${file#$ROOT_DIR/}"
    case "$relative" in
      *natural-earth*) source="Natural Earth" ;;
      *ourairports*) source="OurAirports" ;;
      *nasa*) source="NASA Visible Earth" ;;
      *) source="unknown" ;;
    esac
    printf "%s\t%s\t%s\t%s\n" "$sha" "$bytes" "$relative" "$source"
  done
} > "$MANIFEST"

echo "Wrote $MANIFEST"
