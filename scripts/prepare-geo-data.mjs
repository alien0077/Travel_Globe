import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
const landmarksPath = resolve(root, 'shared/fixtures/landmarks.json');
const naturalEarthDir = resolve(root, 'shared/source-data/natural-earth');
const outputPath = resolve(root, 'shared/offline-packs/core-global/manifest.json');
const boundariesPath = resolve(root, 'shared/offline-packs/core-global/geo-boundaries.json');
const populatedPlacesPath = resolve(root, 'shared/offline-packs/core-global/populated-places.json');
const landmarks = JSON.parse(readFileSync(landmarksPath, 'utf8'));
const regionCodes = [...new Set(landmarks.map((landmark) => landmark.countryCode).filter(Boolean))].sort();
const coastlineZip = resolve(naturalEarthDir, 'ne_110m_coastline.zip');
const countriesZip = resolve(naturalEarthDir, 'ne_110m_admin_0_countries.zip');
const populatedPlacesZip = resolve(naturalEarthDir, 'ne_110m_populated_places.zip');
const coastlineShape = readZipEntry(coastlineZip, 'ne_110m_coastline.shp');
const countriesShape = readZipEntry(countriesZip, 'ne_110m_admin_0_countries.shp');
const populatedPlacesDbf = readZipEntry(populatedPlacesZip, 'ne_110m_populated_places.dbf');
const coastlines = readShapeLines(coastlineShape, 'coastline');
const countryBorders = readShapeLines(countriesShape, 'country-border');
const boundaryFingerprint = createHash('sha256').update(coastlineShape).update(countriesShape).digest('hex');
const populatedPlacesFingerprint = createHash('sha256').update(populatedPlacesDbf).digest('hex');
const populatedPlaces = readPopulatedPlaces(populatedPlacesDbf);
const boundaries = {
  schemaVersion: '1.0.0',
  generatedFrom: `sha256:${boundaryFingerprint}`,
  source: {
    name: 'Natural Earth',
    attribution: 'Made with Natural Earth.',
    urls: {
      coastline: 'https://naturalearth.s3.amazonaws.com/110m_physical/ne_110m_coastline.zip',
      adminCountries: 'https://naturalearth.s3.amazonaws.com/110m_cultural/ne_110m_admin_0_countries.zip'
    }
  },
  contents: {
    coastlines: coastlines.length,
    countryBorders: countryBorders.length,
    points: coastlines.concat(countryBorders).reduce((total, line) => total + line.coordinates.length, 0)
  },
  lines: [...coastlines, ...countryBorders]
};
const populatedPlacesIndex = {
  schemaVersion: '1.0.0',
  generatedFrom: `sha256:${populatedPlacesFingerprint}`,
  source: {
    name: 'Natural Earth',
    attribution: 'Made with Natural Earth.',
    url: 'https://naturalearth.s3.amazonaws.com/110m_cultural/ne_110m_populated_places.zip'
  },
  contents: {
    places: populatedPlaces.length
  },
  places: populatedPlaces
};

const manifest = {
  id: 'core-global',
  version: '1.0.0',
  generatedAt: new Date().toISOString(),
  sources: [
    {
      name: 'Natural Earth',
      license: 'Public domain',
      attribution: 'Made with Natural Earth.',
      sourceUrl: 'https://www.naturalearthdata.com/',
          files: [
            fileEntry('shared/source-data/natural-earth/ne_110m_admin_0_countries.zip'),
            fileEntry('shared/source-data/natural-earth/ne_110m_coastline.zip'),
            fileEntry('shared/source-data/natural-earth/ne_110m_populated_places.zip')
          ]
    },
    {
      name: 'Project landmark fixtures',
      license: 'project-fixture-only',
      attribution: 'Internal Travel Globe fixture data.',
      sourceUrl: 'shared/fixtures/landmarks.json',
      files: [fileEntry('shared/fixtures/landmarks.json')]
    }
  ],
  contents: {
    landmarks: landmarks.length,
    populatedPlaces: populatedPlaces.length,
    regionCodes,
    countryBorders: {
      status: 'prepared',
      lines: countryBorders.length
    },
    coastlines: {
      status: 'prepared',
      lines: coastlines.length
    },
    rtreeIndex: {
      status: 'not-built',
      productionReplacementRequired: true
    }
  },
  indexes: {
    boundaries: 'shared/offline-packs/core-global/geo-boundaries.json',
    populatedPlaces: 'shared/offline-packs/core-global/populated-places.json'
  }
};

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(boundariesPath, `${JSON.stringify(boundaries)}\n`);
writeFileSync(populatedPlacesPath, `${JSON.stringify(populatedPlacesIndex)}\n`);
writeFileSync(outputPath, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`Prepared Natural Earth boundaries with ${boundaries.contents.points} points at ${boundariesPath}`);
console.log(`Prepared Natural Earth populated places with ${populatedPlaces.length} places at ${populatedPlacesPath}`);
console.log(`Prepared offline geo manifest at ${outputPath}`);

function fileEntry(relativePath) {
  const absolutePath = resolve(root, relativePath);
  const data = readFileSync(absolutePath);
  return {
    path: relativePath,
    bytes: statSync(absolutePath).size,
    sha256: createHash('sha256').update(data).digest('hex')
  };
}

function readZipEntry(zipPath, entryName) {
  return execFileSync('unzip', ['-p', zipPath, entryName], { maxBuffer: 20 * 1024 * 1024 });
}

function readPopulatedPlaces(buffer) {
  const records = readDbfRecords(buffer);
  return records
    .map((record, index) => ({
      id: `natural-earth-place-${numberField(record.NE_ID, index)}`,
      name: stringField(record.NAME) || stringField(record.NAMEASCII),
      nameZh: stringField(record.NAME_ZHT) || stringField(record.NAME_ZH),
      label: stringField(record.LABEL),
      type: 'majorCity',
      featureClass: stringField(record.FEATURECLA),
      countryCode: stringField(record.ISO_A2) || stringField(record.ADM0_A3),
      countryName: stringField(record.ADM0NAME),
      admin1: stringField(record.ADM1NAME),
      latitude: numberField(record.LATITUDE),
      longitude: numberField(record.LONGITUDE),
      population: numberField(record.POP_MAX),
      scalerank: numberField(record.SCALERANK, 99),
      labelRank: numberField(record.LABELRANK, 99),
      minZoom: numberField(record.MIN_ZOOM, 9),
      isCapital: numberField(record.ADM0CAP, 0) === 1,
      isWorldCity: numberField(record.WORLDCITY, 0) === 1,
      isMegaCity: numberField(record.MEGACITY, 0) === 1
    }))
    .filter((place) =>
      place.name &&
      Number.isFinite(place.latitude) &&
      Number.isFinite(place.longitude)
    )
    .sort((a, b) =>
      a.labelRank - b.labelRank ||
      b.population - a.population ||
      a.name.localeCompare(b.name)
    );
}

function readDbfRecords(buffer) {
  const recordCount = buffer.readUInt32LE(4);
  const headerLength = buffer.readUInt16LE(8);
  const recordLength = buffer.readUInt16LE(10);
  const fields = [];
  for (let offset = 32; offset < headerLength - 1; offset += 32) {
    fields.push({
      name: buffer.subarray(offset, offset + 11).toString('ascii').replace(/\0.*$/, ''),
      type: String.fromCharCode(buffer[offset + 11]),
      length: buffer[offset + 16]
    });
  }

  const records = [];
  for (let recordIndex = 0; recordIndex < recordCount; recordIndex += 1) {
    const recordOffset = headerLength + recordIndex * recordLength;
    if (buffer[recordOffset] === 0x2a) {
      continue;
    }

    const record = {};
    let fieldOffset = recordOffset + 1;
    for (const field of fields) {
      const raw = buffer.subarray(fieldOffset, fieldOffset + field.length).toString('utf8').trim();
      record[field.name] = raw;
      fieldOffset += field.length;
    }
    records.push(record);
  }
  return records;
}

function stringField(value) {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function numberField(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function readShapeLines(buffer, kind) {
  const shapeType = buffer.readInt32LE(32);
  if (![3, 5].includes(shapeType)) {
    throw new Error(`Unsupported shapefile type ${shapeType}`);
  }

  const lines = [];
  let offset = 100;
  while (offset < buffer.length) {
    const contentLengthBytes = buffer.readInt32BE(offset + 4) * 2;
    const recordStart = offset + 8;
    const recordShapeType = buffer.readInt32LE(recordStart);
    if (recordShapeType !== 0) {
      const partCount = buffer.readInt32LE(recordStart + 36);
      const pointCount = buffer.readInt32LE(recordStart + 40);
      const partsOffset = recordStart + 44;
      const pointsOffset = partsOffset + partCount * 4;
      const partStarts = [];
      for (let partIndex = 0; partIndex < partCount; partIndex += 1) {
        partStarts.push(buffer.readInt32LE(partsOffset + partIndex * 4));
      }

      for (let partIndex = 0; partIndex < partStarts.length; partIndex += 1) {
        const start = partStarts[partIndex];
        const end = partStarts[partIndex + 1] ?? pointCount;
        const coordinates = [];
        for (let pointIndex = start; pointIndex < end; pointIndex += 1) {
          const pointOffset = pointsOffset + pointIndex * 16;
          const longitude = roundCoordinate(buffer.readDoubleLE(pointOffset));
          const latitude = roundCoordinate(buffer.readDoubleLE(pointOffset + 8));
          if (Number.isFinite(latitude) && Number.isFinite(longitude)) {
            coordinates.push([latitude, longitude]);
          }
        }
        if (coordinates.length >= 2) {
          lines.push({ kind, coordinates: simplifyCoordinates(coordinates) });
        }
      }
    }
    offset = recordStart + contentLengthBytes;
  }

  return lines;
}

function simplifyCoordinates(coordinates) {
  if (coordinates.length <= 80) {
    return coordinates;
  }
  const stride = Math.ceil(coordinates.length / 80);
  const simplified = coordinates.filter((_, index) => index % stride === 0);
  const last = coordinates[coordinates.length - 1];
  const simplifiedLast = simplified[simplified.length - 1];
  if (simplifiedLast[0] !== last[0] || simplifiedLast[1] !== last[1]) {
    simplified.push(last);
  }
  return simplified;
}

function roundCoordinate(value) {
  return Math.round(value * 1000) / 1000;
}
