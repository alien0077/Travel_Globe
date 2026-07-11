import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
const sourceDir = resolve(root, 'shared/source-data/ourairports');
const outputPath = resolve(root, 'shared/offline-packs/core-global/airports-index.json');

const sourceTexts = {
  airports: readFileSync(resolve(sourceDir, 'airports.csv'), 'utf8'),
  runways: readFileSync(resolve(sourceDir, 'runways.csv'), 'utf8'),
  countries: readFileSync(resolve(sourceDir, 'countries.csv'), 'utf8'),
  regions: readFileSync(resolve(sourceDir, 'regions.csv'), 'utf8')
};
const sourceFingerprint = createHash('sha256')
  .update(sourceTexts.airports)
  .update(sourceTexts.runways)
  .update(sourceTexts.countries)
  .update(sourceTexts.regions)
  .digest('hex');

const airports = parseCsv(sourceTexts.airports);
const runways = parseCsv(sourceTexts.runways);
const countries = parseCsv(sourceTexts.countries);
const regions = parseCsv(sourceTexts.regions);

const countryNames = new Map(countries.map((country) => [country.code, country.name]));
const regionNames = new Map(regions.map((region) => [region.code, region.name]));
const runwayStats = new Map();

for (const runway of runways) {
  const airportRef = runway.airport_ref;
  if (!airportRef) {
    continue;
  }
  const lengthFeet = Number(runway.length_ft) || 0;
  const stats = runwayStats.get(airportRef) ?? { runwayCount: 0, longestRunwayFeet: 0 };
  stats.runwayCount += 1;
  stats.longestRunwayFeet = Math.max(stats.longestRunwayFeet, lengthFeet);
  runwayStats.set(airportRef, stats);
}

const indexedAirports = airports
  .filter((airport) => shouldIndexAirport(airport))
  .map((airport) => {
    const stats = runwayStats.get(airport.id) ?? { runwayCount: 0, longestRunwayFeet: 0 };
    return {
      id: `airport-${airport.iata_code.toLowerCase()}`,
      ourairportsId: Number(airport.id),
      ident: airport.ident,
      type: airport.type,
      name: airport.name,
      iataCode: airport.iata_code,
      icaoCode: airport.icao_code || undefined,
      countryCode: airport.iso_country,
      countryName: countryNames.get(airport.iso_country) ?? airport.iso_country,
      regionCode: airport.iso_region,
      regionName: regionNames.get(airport.iso_region) ?? airport.iso_region,
      municipality: airport.municipality || airport.name,
      latitude: Number(airport.latitude_deg),
      longitude: Number(airport.longitude_deg),
      elevationFeet: numberOrUndefined(airport.elevation_ft),
      scheduledService: airport.scheduled_service === 'yes',
      runwayCount: stats.runwayCount,
      longestRunwayFeet: stats.longestRunwayFeet || undefined
    };
  })
  .sort((left, right) => left.iataCode.localeCompare(right.iataCode));

const output = {
  schemaVersion: '1.0.0',
  generatedFrom: `sha256:${sourceFingerprint}`,
  source: {
    name: 'OurAirports',
    attribution: 'Airport and runway data provided by OurAirports.',
    urls: {
      airports: 'https://davidmegginson.github.io/ourairports-data/airports.csv',
      runways: 'https://davidmegginson.github.io/ourairports-data/runways.csv',
      frequencies: 'https://davidmegginson.github.io/ourairports-data/airport-frequencies.csv',
      navaids: 'https://davidmegginson.github.io/ourairports-data/navaids.csv',
      countries: 'https://davidmegginson.github.io/ourairports-data/countries.csv',
      regions: 'https://davidmegginson.github.io/ourairports-data/regions.csv'
    }
  },
  contents: {
    airports: indexedAirports.length,
    scheduledServiceAirports: indexedAirports.filter((airport) => airport.scheduledService).length
  },
  airports: indexedAirports
};

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, `${JSON.stringify(output, null, 2)}\n`);
console.log(`Prepared OurAirports index with ${indexedAirports.length} airports at ${outputPath}`);

function shouldIndexAirport(airport) {
  return (
    /^[A-Z0-9]{3}$/.test(airport.iata_code) &&
    airport.type !== 'closed' &&
    Number.isFinite(Number(airport.latitude_deg)) &&
    Number.isFinite(Number(airport.longitude_deg))
  );
}

function numberOrUndefined(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];

    if (char === '"') {
      if (inQuotes && next === '"') {
        field += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (char === ',' && !inQuotes) {
      row.push(field);
      field = '';
      continue;
    }

    if ((char === '\n' || char === '\r') && !inQuotes) {
      if (char === '\r' && next === '\n') {
        index += 1;
      }
      row.push(field);
      field = '';
      if (row.some((value) => value.length > 0)) {
        rows.push(row);
      }
      row = [];
      continue;
    }

    field += char;
  }

  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }

  const [headers, ...records] = rows;
  return records.map((record) =>
    Object.fromEntries(headers.map((header, index) => [header, record[index] ?? '']))
  );
}
