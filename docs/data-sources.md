# Data Sources

Travel Globe should support every useful geographic layer, but production packs must keep source licenses explicit.

## Approved First-Pack Sources

- Natural Earth: country borders, coastlines, populated places, and small-scale labels. Public domain; attribution optional but recommended as `Made with Natural Earth`.
- NASA Blue Marble / NASA Earth imagery and Three.js example Earth textures: globe, night-lights, cloud, and specular texture candidates. NASA media generally may be used for factual, educational, and informational purposes, but the app must not imply NASA endorsement and must avoid NASA marks as branding.
- OurAirports: airports, runways, frequencies, navaids, countries, and regions. Public domain; credit is not required, but Travel Globe should still show `Airport and runway data provided by OurAirports.` in About / Data Sources.
- GeoNames cities15000: global city/place labels for offline route-nearby lookup. GeoNames data is available under CC BY 4.0 and requires attribution such as `Contains GeoNames data available under CC BY 4.0.`
- OpenFlights routes.dat: historical airline route graph for airport context and aircraft/equipment-code fallback. ODbL/DbCL attribution and share-alike obligations apply, so it must be labeled as historical route graph data and never presented as live schedules, filed routes, waypoint geometry, or navigation data.

## Optional / Isolated Pack

- OpenStreetMap: roads, trails, shops, stations, and detailed POI. ODbL requires attribution and share-alike handling for adapted databases. Keep OSM in a separate optional pack and do not merge it into proprietary or incompatible datasets.
- NASA GIBS: optional near-real-time visual satellite imagery tiles. GIBS asks for acknowledgement of imagery services from NASA GIBS / ESDIS.
- NOAA AviationWeather Data API: free METAR/TAF source for aviation weather overlays. Use for weather observation summaries, not for route authority or navigation.
- Open-Meteo: no-key forecast API candidate for route cloud cover, visibility, pressure-level cloud cover, and non-aviation weather fallback. Confirm usage tier before production-scale use.
- EOG VIIRS Nighttime Lights: offline light-pollution calibration candidate. Many products are CC BY 4.0; use annual VNL for stable offline brightness calibration rather than live per-flight changes.

## Source URLs

- Natural Earth terms: https://www.naturalearthdata.com/about/terms-of-use/
- NASA image and media guidelines: https://www.nasa.gov/nasa-brand-center/images-and-media/
- OurAirports data: https://ourairports.com/data/
- GeoNames export: https://download.geonames.org/export/dump/
- GeoNames license/credits: https://www.geonames.org/
- OpenFlights data: https://openflights.org/data.php
- NOAA AviationWeather Data API: https://aviationweather.gov/data/api/
- Open-Meteo forecast API: https://open-meteo.com/en/docs
- NASA GIBS API docs: https://nasa-gibs.github.io/gibs-api-docs/
- EOG VIIRS Nighttime Lights: https://eogdata.mines.edu/products/vnl/
- OpenStreetMap copyright and license: https://www.openstreetmap.org/copyright

## Pack Policy

- Each pack must include `source`, `license`, `attribution`, `downloadedAt`, and `sourceUrl` metadata.
- Each transformed dataset must keep raw source data separate from processed app indexes.
- OSM-derived data must never be silently mixed into non-ODbL datasets.
- Production builds must include an attribution surface for every installed pack.

## Downloaded Baseline

The current repository includes a downloaded source baseline under `shared/source-data/`:

- Natural Earth 110m baseline archives, 50m admin/coastline archives, 10m populated places, and 10m geography region point archives
- OurAirports airports, runways, frequencies, navaids, countries, and regions CSV files
- GeoNames `cities15000.zip`
- OpenFlights `routes.dat`
- NASA Visible Earth Blue Marble `land_ocean_ice_2048.jpg`
- Bundled Earth lights, clouds, and specular textures from the Three.js example texture set

Run `scripts/download-geo-data.sh` to refresh the baseline and regenerate `shared/source-data/source-manifest.tsv`.
Run `npm --prefix replay-engine run prepare:airports` after refreshing OurAirports data to regenerate `shared/offline-packs/core-global/airports-index.json`.
Run `npm --prefix replay-engine run prepare:geo` after refreshing Natural Earth or GeoNames data to regenerate the core global atlas indexes and spatial grid.

OSM is intentionally not downloaded into the baseline yet. It remains an optional isolated pack because ODbL attribution and share-alike requirements must stay separate from the permissive Natural Earth / NASA / OurAirports pack and the CC BY GeoNames layer.

## Flight And Weather Boundary

- Do not scrape airline, OTA, FlightRadar24, FlightAware, or airport web pages into committed fallback data unless their terms explicitly allow redistribution and product use.
- aviationstack remains the user-key live lookup path for flight-number origin/destination, airline, timing, and aircraft data. When OpenFlights has a matching origin-destination pair, Replay Engine may use its equipment code only if no aircraft type was provided by aviationstack, cache, or the user. It does not override origin/destination/time/airline, and the planned route remains Great Circle endpoint interpolation until a filed-route provider is added.
- NOAA AviationWeather METAR/TAF and Open-Meteo are the preferred free weather candidates. NASA GIBS is better for visual satellite layers than structured per-airport weather.
- Current runtime cloud variation is simulated from replay position/time; it must be labeled as simulated until a live weather provider is wired.
