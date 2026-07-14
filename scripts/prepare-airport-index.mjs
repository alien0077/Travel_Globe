import { mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
const sourceDir = resolve(root, 'shared/source-data/ourairports');
const outputPath = resolve(root, 'shared/offline-packs/core-global/airports-index.json');
const contextOutputPath = resolve(root, 'shared/offline-packs/core-global/aviation-context-index.json');

const sourceTexts = {
  airports: readFileSync(resolve(sourceDir, 'airports.csv'), 'utf8'),
  runways: readFileSync(resolve(sourceDir, 'runways.csv'), 'utf8'),
  frequencies: readFileSync(resolve(sourceDir, 'frequencies.csv'), 'utf8'),
  navaids: readFileSync(resolve(sourceDir, 'navaids.csv'), 'utf8'),
  countries: readFileSync(resolve(sourceDir, 'countries.csv'), 'utf8'),
  regions: readFileSync(resolve(sourceDir, 'regions.csv'), 'utf8')
};
const sourceFingerprint = createHash('sha256')
  .update(sourceTexts.airports)
  .update(sourceTexts.runways)
  .update(sourceTexts.frequencies)
  .update(sourceTexts.navaids)
  .update(sourceTexts.countries)
  .update(sourceTexts.regions)
  .digest('hex');

const airports = parseCsv(sourceTexts.airports);
const runways = parseCsv(sourceTexts.runways);
const frequencies = parseCsv(sourceTexts.frequencies);
const navaids = parseCsv(sourceTexts.navaids);
const countries = parseCsv(sourceTexts.countries);
const regions = parseCsv(sourceTexts.regions);

const countryNames = new Map(countries.map((country) => [country.code, country.name]));
const regionNames = new Map(regions.map((region) => [region.code, region.name]));
const runwayStats = new Map();
const airportIdentToIata = new Map();
const airportRefToIata = new Map();

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

for (const airport of indexedAirports) {
  airportIdentToIata.set(airport.ident, airport.iataCode);
  airportRefToIata.set(String(airport.ourairportsId), airport.iataCode);
}

const frequenciesByAirport = new Map();
for (const frequency of frequencies) {
  const iataCode = airportRefToIata.get(frequency.airport_ref);
  if (!iataCode) {
    continue;
  }
  const frequencyMhz = Number(frequency.frequency_mhz);
  const list = frequenciesByAirport.get(iataCode) ?? [];
  list.push({
    type: frequency.type || 'UNKNOWN',
    description: frequency.description || undefined,
    frequencyMhz: Number.isFinite(frequencyMhz) ? frequencyMhz : undefined
  });
  frequenciesByAirport.set(iataCode, list);
}

const indexedNavaids = navaids
  .map((navaid) => {
    const latitude = Number(navaid.latitude_deg);
    const longitude = Number(navaid.longitude_deg);
    const frequencyKhz = Number(navaid.frequency_khz);
    return {
      id: `navaid-${navaid.id}`,
      ident: navaid.ident,
      name: navaid.name,
      type: navaid.type,
      countryCode: navaid.iso_country,
      associatedAirportIata: airportIdentToIata.get(navaid.associated_airport) ?? undefined,
      latitude,
      longitude,
      frequencyKhz: Number.isFinite(frequencyKhz) ? frequencyKhz : undefined,
      usageType: navaid.usageType || undefined,
      power: navaid.power || undefined
    };
  })
  .filter((navaid) => navaid.ident && Number.isFinite(navaid.latitude) && Number.isFinite(navaid.longitude))
  .sort((left, right) => left.ident.localeCompare(right.ident));

const airportContexts = indexedAirports
  .map((airport) => ({
    iataCode: airport.iataCode,
    frequencies: (frequenciesByAirport.get(airport.iataCode) ?? []).sort((left, right) =>
      left.type.localeCompare(right.type)
    ),
    navaids: indexedNavaids.filter((navaid) => navaid.associatedAirportIata === airport.iataCode).slice(0, 12)
  }))
  .filter((context) => context.frequencies.length > 0 || context.navaids.length > 0);

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
    scheduledServiceAirports: indexedAirports.filter((airport) => airport.scheduledService).length,
    airportContexts: airportContexts.length,
    navaids: indexedNavaids.length
  },
  airports: indexedAirports
};

const contextOutput = {
  schemaVersion: '1.0.0',
  generatedFrom: `sha256:${sourceFingerprint}`,
  source: output.source,
  contents: {
    airportContexts: airportContexts.length,
    frequencies: [...frequenciesByAirport.values()].reduce((total, list) => total + list.length, 0),
    navaids: indexedNavaids.length
  },
  contexts: airportContexts,
  navaids: indexedNavaids
};

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, `${JSON.stringify(output, null, 2)}\n`);
writeFileSync(contextOutputPath, `${JSON.stringify(contextOutput, null, 2)}\n`);
writeFileSync(
  resolve(root, 'shared/offline-packs/core-global/ourairports-manifest.json'),
  `${JSON.stringify(buildOurAirportsManifest(sourceFingerprint, output, contextOutput), null, 2)}\n`
);
console.log(`Prepared OurAirports index with ${indexedAirports.length} airports at ${outputPath}`);
console.log(`Prepared aviation context index with ${airportContexts.length} airport contexts at ${contextOutputPath}`);

function shouldIndexAirport(airport) {
  return (
    /^[A-Z0-9]{3}$/.test(airport.iata_code) &&
    airport.scheduled_service === 'yes' &&
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

function buildOurAirportsManifest(fingerprint, airportOutput, aviationOutput) {
  return {
    id: 'ourairports-core',
    version: '1.0.0',
    generatedFrom: `sha256:${fingerprint}`,
    source: airportOutput.source,
    files: [
      fileEntry('shared/source-data/ourairports/airports.csv'),
      fileEntry('shared/source-data/ourairports/runways.csv'),
      fileEntry('shared/source-data/ourairports/frequencies.csv'),
      fileEntry('shared/source-data/ourairports/navaids.csv'),
      fileEntry('shared/source-data/ourairports/countries.csv'),
      fileEntry('shared/source-data/ourairports/regions.csv')
    ],
    indexes: {
      airports: {
        path: 'shared/offline-packs/core-global/airports-index.json',
        records: airportOutput.contents.airports
      },
      aviationContext: {
        path: 'shared/offline-packs/core-global/aviation-context-index.json',
        airportContexts: aviationOutput.contents.airportContexts,
        frequencies: aviationOutput.contents.frequencies,
        navaids: aviationOutput.contents.navaids
      }
    }
  };
}

function fileEntry(relativePath) {
  const path = resolve(root, relativePath);
  const data = readFileSync(path);
  return {
    path: relativePath,
    bytes: statSync(path).size,
    sha256: createHash('sha256').update(data).digest('hex')
  };
}
