import { mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
const sourceDir = resolve(root, 'shared/source-data/ourairports');
const openFlightsDir = resolve(root, 'shared/source-data/openflights');
const outputPath = resolve(root, 'shared/offline-packs/core-global/airports-index.json');
const contextOutputPath = resolve(root, 'shared/offline-packs/core-global/aviation-context-index.json');
const publicPackDir = resolve(root, 'replay-engine/public/offline-packs/core-global');

const sourceTexts = {
  airports: readFileSync(resolve(sourceDir, 'airports.csv'), 'utf8'),
  runways: readFileSync(resolve(sourceDir, 'runways.csv'), 'utf8'),
  frequencies: readFileSync(resolve(sourceDir, 'frequencies.csv'), 'utf8'),
  navaids: readFileSync(resolve(sourceDir, 'navaids.csv'), 'utf8'),
  countries: readFileSync(resolve(sourceDir, 'countries.csv'), 'utf8'),
  regions: readFileSync(resolve(sourceDir, 'regions.csv'), 'utf8')
};
const openFlightsRoutesText = readOptionalText(resolve(openFlightsDir, 'routes.dat'));
const sourceFingerprint = createHash('sha256')
  .update(sourceTexts.airports)
  .update(sourceTexts.runways)
  .update(sourceTexts.frequencies)
  .update(sourceTexts.navaids)
  .update(sourceTexts.countries)
  .update(sourceTexts.regions)
  .update(openFlightsRoutesText)
  .digest('hex');

const airports = parseCsv(sourceTexts.airports);
const runways = parseCsv(sourceTexts.runways);
const frequencies = parseCsv(sourceTexts.frequencies);
const navaids = parseCsv(sourceTexts.navaids);
const countries = parseCsv(sourceTexts.countries);
const regions = parseCsv(sourceTexts.regions);
const openFlightsRoutes = parseOpenFlightsRoutes(openFlightsRoutesText);

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

const routeGraphByAirport = buildOpenFlightsRouteGraph(openFlightsRoutes, new Set(indexedAirports.map((airport) => airport.iataCode)));

const airportContexts = indexedAirports
  .map((airport) => ({
    iataCode: airport.iataCode,
    frequencies: (frequenciesByAirport.get(airport.iataCode) ?? []).sort((left, right) =>
      left.type.localeCompare(right.type)
    ),
    navaids: indexedNavaids.filter((navaid) => navaid.associatedAirportIata === airport.iataCode).slice(0, 12),
    routeGraph: routeGraphByAirport.get(airport.iataCode)
  }))
  .filter((context) => context.frequencies.length > 0 || context.navaids.length > 0 || context.routeGraph);

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
  routeGraphSource: {
    name: 'OpenFlights',
    license: 'ODbL / DbCL',
    attribution: 'Route graph derived from OpenFlights routes.dat.',
    sourceUrl: 'https://openflights.org/data.php',
    note: 'Historical route graph, not a live timetable. OpenFlights states route data is static and not suitable for navigation.'
  },
  contents: {
    airports: indexedAirports.length,
    scheduledServiceAirports: indexedAirports.filter((airport) => airport.scheduledService).length,
    airportContexts: airportContexts.length,
    navaids: indexedNavaids.length,
    openFlightsRoutes: openFlightsRoutes.length,
    openFlightsRouteAirports: routeGraphByAirport.size
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
    navaids: indexedNavaids.length,
    openFlightsRoutes: openFlightsRoutes.length,
    openFlightsRouteAirports: routeGraphByAirport.size
  },
  routeGraphSource: output.routeGraphSource,
  contexts: airportContexts,
  navaids: indexedNavaids
};

const ourAirportsManifest = buildOurAirportsManifest(sourceFingerprint, output, contextOutput);

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, `${JSON.stringify(output, null, 2)}\n`);
writeFileSync(contextOutputPath, `${JSON.stringify(contextOutput, null, 2)}\n`);
writeFileSync(
  resolve(root, 'shared/offline-packs/core-global/ourairports-manifest.json'),
  `${JSON.stringify(ourAirportsManifest, null, 2)}\n`
);
mirrorPublicPackAsset('airports-index.json', output, true);
mirrorPublicPackAsset('aviation-context-index.json', contextOutput, true);
mirrorPublicPackAsset('ourairports-manifest.json', ourAirportsManifest, true);
console.log(`Prepared OurAirports index with ${indexedAirports.length} airports at ${outputPath}`);
console.log(`Prepared aviation context index with ${airportContexts.length} airport contexts at ${contextOutputPath}`);
console.log(`Prepared OpenFlights route graph with ${openFlightsRoutes.length} historical routes`);

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

function readOptionalText(path) {
  try {
    return readFileSync(path, 'utf8');
  } catch (error) {
    if (error?.code === 'ENOENT') {
      return '';
    }
    throw error;
  }
}

function parseOpenFlightsRoutes(text) {
  if (!text.trim()) {
    return [];
  }
  return parseCsvRows(text)
    .map((row) => ({
      airline: nullIfMissing(row[0]),
      sourceAirport: nullIfMissing(row[2]),
      destinationAirport: nullIfMissing(row[4]),
      codeshare: row[6] === 'Y',
      stops: Number(row[7]) || 0,
      equipment: nullIfMissing(row[8])
    }))
    .filter((route) =>
      route.sourceAirport &&
      route.destinationAirport &&
      route.stops === 0 &&
      /^[A-Z0-9]{3}$/.test(route.sourceAirport) &&
      /^[A-Z0-9]{3}$/.test(route.destinationAirport)
    );
}

function parseCsvRows(text) {
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

  return rows;
}

function nullIfMissing(value) {
  if (!value || value === '\\N') {
    return undefined;
  }
  return value.trim();
}

function buildOpenFlightsRouteGraph(routes, knownIataCodes) {
  const summaries = new Map();
  for (const route of routes) {
    const source = route.sourceAirport;
    const destination = route.destinationAirport;
    if (!knownIataCodes.has(source) || !knownIataCodes.has(destination)) {
      continue;
    }
    addRouteGraphEntry(summaries, source, destination, route, 'outgoing');
    addRouteGraphEntry(summaries, destination, source, route, 'incoming');
  }

  const output = new Map();
  for (const [iataCode, summary] of summaries.entries()) {
    output.set(iataCode, {
      source: 'OpenFlights historical route graph',
      outgoingRoutes: summary.outgoingRoutes,
      incomingRoutes: summary.incomingRoutes,
      destinations: rankedEntries(summary.destinations, Number.POSITIVE_INFINITY).map((entry) => ({
        ...entry,
        aircraftTypes: rankedEntries(summary.destinationAircraftTypes.get(entry.code) ?? new Map(), 8).map((aircraft) => aircraft.code)
      })),
      topDestinations: rankedEntries(summary.destinations, 12),
      airlines: rankedEntries(summary.airlines, 12).map((entry) => entry.code),
      aircraftTypes: rankedEntries(summary.aircraftTypes, 12).map((entry) => entry.code)
    });
  }
  return output;
}

function addRouteGraphEntry(summaries, airport, otherAirport, route, direction) {
  const summary = summaries.get(airport) ?? {
    outgoingRoutes: 0,
    incomingRoutes: 0,
    destinations: new Map(),
    destinationAircraftTypes: new Map(),
    airlines: new Map(),
    aircraftTypes: new Map()
  };
  if (direction === 'outgoing') {
    summary.outgoingRoutes += 1;
    increment(summary.destinations, otherAirport);
    const aircraftTypesForDestination = summary.destinationAircraftTypes.get(otherAirport) ?? new Map();
    for (const aircraftType of openFlightsEquipmentTypes(route.equipment)) {
      increment(aircraftTypesForDestination, aircraftType);
    }
    summary.destinationAircraftTypes.set(otherAirport, aircraftTypesForDestination);
  } else {
    summary.incomingRoutes += 1;
  }
  if (route.airline) {
    increment(summary.airlines, route.airline);
  }
  for (const aircraftType of openFlightsEquipmentTypes(route.equipment)) {
    increment(summary.aircraftTypes, aircraftType);
  }
  summaries.set(airport, summary);
}

function openFlightsEquipmentTypes(value) {
  return (value ?? '')
    .split(/\s+/)
    .map((code) => code.trim().toUpperCase())
    .filter((code) => /^[A-Z0-9]{2,4}$/.test(code));
}

function increment(map, key) {
  map.set(key, (map.get(key) ?? 0) + 1);
}

function rankedEntries(map, limit) {
  return [...map.entries()]
    .map(([code, count]) => ({ code, count }))
    .sort((left, right) => right.count - left.count || left.code.localeCompare(right.code))
    .slice(0, limit);
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
      fileEntry('shared/source-data/ourairports/regions.csv'),
      ...(openFlightsRoutesText ? [fileEntry('shared/source-data/openflights/routes.dat')] : [])
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
    },
    payloads: {
      aviationCore: [
        generatedJsonEntry('shared/offline-packs/core-global/airports-index.json', airportOutput),
        generatedJsonEntry('shared/offline-packs/core-global/aviation-context-index.json', aviationOutput)
      ]
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

function generatedJsonEntry(relativePath, value) {
  const data = Buffer.from(`${JSON.stringify(value, null, 2)}\n`);
  return {
    path: relativePath,
    bytes: data.length,
    sha256: createHash('sha256').update(data).digest('hex')
  };
}

function mirrorPublicPackAsset(filename, value, pretty = false) {
  mkdirSync(publicPackDir, { recursive: true });
  const json = pretty ? JSON.stringify(value, null, 2) : JSON.stringify(value);
  writeFileSync(resolve(publicPackDir, filename), `${json}\n`);
}
