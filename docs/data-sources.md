# Data Sources

Travel Globe should support every useful geographic layer, but production packs must keep source licenses explicit.

## Approved First-Pack Sources

- Natural Earth: country borders, coastlines, populated places, and small-scale labels. Public domain; attribution optional but recommended as `Made with Natural Earth`.
- NASA Blue Marble / NASA Earth imagery: globe texture candidates. NASA media generally may be used for factual, educational, and informational purposes, but the app must not imply NASA endorsement and must avoid NASA marks as branding.
- OurAirports: airports, runways, frequencies, navaids, countries, and regions. Public domain; credit is not required, but Travel Globe should still show `Airport and runway data provided by OurAirports.` in About / Data Sources.

## Optional / Isolated Pack

- OpenStreetMap: roads, trails, shops, stations, and detailed POI. ODbL requires attribution and share-alike handling for adapted databases. Keep OSM in a separate optional pack and do not merge it into proprietary or incompatible datasets.

## Source URLs

- Natural Earth terms: https://www.naturalearthdata.com/about/terms-of-use/
- NASA image and media guidelines: https://www.nasa.gov/nasa-brand-center/images-and-media/
- OurAirports data: https://ourairports.com/data/
- OpenStreetMap copyright and license: https://www.openstreetmap.org/copyright

## Pack Policy

- Each pack must include `source`, `license`, `attribution`, `downloadedAt`, and `sourceUrl` metadata.
- Each transformed dataset must keep raw source data separate from processed app indexes.
- OSM-derived data must never be silently mixed into non-ODbL datasets.
- Production builds must include an attribution surface for every installed pack.

## Downloaded Baseline

The current repository includes a downloaded source baseline under `shared/source-data/`:

- Natural Earth 110m admin countries, populated places, land, and coastline archives
- OurAirports airports, runways, frequencies, navaids, countries, and regions CSV files
- NASA Visible Earth Blue Marble `land_ocean_ice_2048.jpg`

Run `scripts/download-geo-data.sh` to refresh the baseline and regenerate `shared/source-data/source-manifest.tsv`.
Run `npm --prefix replay-engine run prepare:airports` after refreshing OurAirports data to regenerate `shared/offline-packs/core-global/airports-index.json`.

OSM is intentionally not downloaded into the baseline yet. It remains an optional isolated pack because ODbL attribution and share-alike requirements must stay separate from the permissive Natural Earth / NASA / OurAirports pack.
