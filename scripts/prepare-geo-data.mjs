import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
const landmarksPath = resolve(root, 'shared/fixtures/landmarks.json');
const naturalEarthDir = resolve(root, 'shared/source-data/natural-earth');
const geonamesDir = resolve(root, 'shared/source-data/geonames');
const publicPackDir = resolve(root, 'replay-engine/public/offline-packs/core-global');
const outputPath = resolve(root, 'shared/offline-packs/core-global/manifest.json');
const boundariesPath = resolve(root, 'shared/offline-packs/core-global/geo-boundaries.json');
const populatedPlacesPath = resolve(root, 'shared/offline-packs/core-global/populated-places.json');
const geographyRegionsPath = resolve(root, 'shared/offline-packs/core-global/geography-regions.json');
const globalPlacesPath = resolve(root, 'shared/offline-packs/core-global/global-places.json');
const spatialIndexPath = resolve(root, 'shared/offline-packs/core-global/geo-spatial-index.json');
const landmarks = JSON.parse(readFileSync(landmarksPath, 'utf8'));
const regionCodes = [...new Set(landmarks.map((landmark) => landmark.countryCode).filter(Boolean))].sort();
const coastlineDataset = naturalEarthDataset('ne_50m_coastline', 'ne_110m_coastline');
const countriesDataset = naturalEarthDataset('ne_50m_admin_0_countries', 'ne_110m_admin_0_countries');
const populatedPlacesDataset = naturalEarthDataset('ne_10m_populated_places', 'ne_110m_populated_places');
const geographyRegionsDataset = naturalEarthDataset('ne_10m_geography_regions_points');
const geonamesDataset = geonamesSource('cities15000');
const coastlineShape = readZipEntry(coastlineDataset.zipPath, `${coastlineDataset.name}.shp`);
const countriesShape = readZipEntry(countriesDataset.zipPath, `${countriesDataset.name}.shp`);
const populatedPlacesDbf = readZipEntry(populatedPlacesDataset.zipPath, `${populatedPlacesDataset.name}.dbf`);
const geographyRegionsDbf = readZipEntry(geographyRegionsDataset.zipPath, `${geographyRegionsDataset.name}.dbf`);
const geonamesCitiesText = readZipEntry(geonamesDataset.zipPath, `${geonamesDataset.name}.txt`).toString('utf8');
const coastlines = readShapeLines(coastlineShape, 'coastline');
const countryBorders = readShapeLines(countriesShape, 'country-border');
const boundaryFingerprint = createHash('sha256').update(coastlineShape).update(countriesShape).digest('hex');
const populatedPlacesFingerprint = createHash('sha256').update(populatedPlacesDbf).digest('hex');
const geographyRegionsFingerprint = createHash('sha256').update(geographyRegionsDbf).digest('hex');
const geonamesFingerprint = createHash('sha256').update(geonamesCitiesText).digest('hex');
const populatedPlaces = readPopulatedPlaces(populatedPlacesDbf);
const geographyRegions = readGeographyRegions(geographyRegionsDbf);
const geonamesCities = readGeoNamesCities(geonamesCitiesText);
const globalPlaces = mergeGlobalPlaces([
  ...landmarks.map(normalizeFixtureLandmark),
  ...populatedPlaces.map(normalizeNaturalEarthPlace),
  ...geographyRegions.map(normalizeNaturalEarthRegion),
  ...geonamesCities.map(normalizeGeoNamesCity)
]);
const spatialIndex = buildSpatialIndex(globalPlaces, [...coastlines, ...countryBorders]);
const boundaries = {
  schemaVersion: '1.0.0',
  generatedFrom: `sha256:${boundaryFingerprint}`,
  source: {
    name: 'Natural Earth',
    attribution: 'Made with Natural Earth.',
    urls: {
      coastline: naturalEarthUrl(coastlineDataset),
      adminCountries: naturalEarthUrl(countriesDataset)
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
    url: naturalEarthUrl(populatedPlacesDataset)
  },
  contents: {
    places: populatedPlaces.length
  },
  places: populatedPlaces
};
const geographyRegionsIndex = {
  schemaVersion: '1.0.0',
  generatedFrom: `sha256:${geographyRegionsFingerprint}`,
  source: {
    name: 'Natural Earth',
    attribution: 'Made with Natural Earth.',
    url: naturalEarthUrl(geographyRegionsDataset)
  },
  contents: {
    regions: geographyRegions.length
  },
  regions: geographyRegions
};
const globalPlacesIndex = {
  schemaVersion: '1.0.0',
  generatedFrom: {
    fixtureLandmarks: fileEntry('shared/fixtures/landmarks.json').sha256,
    naturalEarthPopulatedPlaces: `sha256:${populatedPlacesFingerprint}`,
    naturalEarthGeographyRegions: `sha256:${geographyRegionsFingerprint}`,
    geonamesCities: `sha256:${geonamesFingerprint}`
  },
  sources: [
    {
      name: 'Project landmark fixtures',
      attribution: 'Internal Travel Globe fixture data.'
    },
    {
      name: 'Natural Earth',
      attribution: 'Made with Natural Earth.'
    },
    {
      name: 'GeoNames',
      attribution: 'Contains GeoNames data available under CC BY 4.0.'
    }
  ],
  contents: {
    features: globalPlaces.length,
    curatedLandmarks: landmarks.length,
    naturalEarthPopulatedPlaces: populatedPlaces.length,
    naturalEarthGeographyRegions: geographyRegions.length,
    geonamesCities: geonamesCities.length
  },
  features: globalPlaces
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
            fileEntry(relativePathForDataset(countriesDataset)),
            fileEntry(relativePathForDataset(coastlineDataset)),
            fileEntry(relativePathForDataset(populatedPlacesDataset)),
            fileEntry(relativePathForDataset(geographyRegionsDataset))
          ]
    },
    {
      name: 'Project landmark fixtures',
      license: 'project-fixture-only',
      attribution: 'Internal Travel Globe fixture data.',
      sourceUrl: 'shared/fixtures/landmarks.json',
      files: [fileEntry('shared/fixtures/landmarks.json')]
    },
    {
      name: 'GeoNames',
      license: 'CC BY 4.0',
      attribution: 'Contains GeoNames data available under CC BY 4.0.',
      sourceUrl: 'https://download.geonames.org/export/dump/cities15000.zip',
      files: [fileEntry(relativePathForGeoNames(geonamesDataset))]
    }
  ],
  contents: {
    landmarks: landmarks.length,
    populatedPlaces: populatedPlaces.length,
    geographyRegions: geographyRegions.length,
    geonamesCities: geonamesCities.length,
    globalPlaces: globalPlaces.length,
    regionCodes,
    countryBorders: {
      status: 'prepared',
      lines: countryBorders.length
    },
    coastlines: {
      status: 'prepared',
      lines: coastlines.length
    },
    spatialIndex: {
      status: 'prepared-grid',
      cellDegrees: spatialIndex.cellDegrees,
      cells: spatialIndex.contents.cells,
      indexedFeatures: spatialIndex.contents.indexedFeatures,
      indexedBoundaryLines: spatialIndex.contents.indexedBoundaryLines,
      pointInPolygonQueryRequired: true
    }
  },
  indexes: {
    boundaries: 'shared/offline-packs/core-global/geo-boundaries.json',
    populatedPlaces: 'shared/offline-packs/core-global/populated-places.json',
    geographyRegions: 'shared/offline-packs/core-global/geography-regions.json',
    globalPlaces: 'shared/offline-packs/core-global/global-places.json',
    spatialIndex: 'shared/offline-packs/core-global/geo-spatial-index.json'
  },
  payloads: {
    coreGlobalAtlas: [
      generatedJsonEntry('shared/offline-packs/core-global/geo-boundaries.json', boundaries),
      generatedJsonEntry('shared/offline-packs/core-global/populated-places.json', populatedPlacesIndex),
      generatedJsonEntry('shared/offline-packs/core-global/geography-regions.json', geographyRegionsIndex),
      generatedJsonEntry('shared/offline-packs/core-global/global-places.json', globalPlacesIndex),
      generatedJsonEntry('shared/offline-packs/core-global/geo-spatial-index.json', spatialIndex)
    ]
  }
};

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(boundariesPath, `${JSON.stringify(boundaries)}\n`);
writeFileSync(populatedPlacesPath, `${JSON.stringify(populatedPlacesIndex)}\n`);
writeFileSync(geographyRegionsPath, `${JSON.stringify(geographyRegionsIndex)}\n`);
writeFileSync(globalPlacesPath, `${JSON.stringify(globalPlacesIndex)}\n`);
writeFileSync(spatialIndexPath, `${JSON.stringify(spatialIndex)}\n`);
writeFileSync(outputPath, `${JSON.stringify(manifest, null, 2)}\n`);
mirrorPublicPackAsset('manifest.json', manifest, true);
mirrorPublicPackAsset('geo-boundaries.json', boundaries);
mirrorPublicPackAsset('populated-places.json', populatedPlacesIndex);
mirrorPublicPackAsset('geography-regions.json', geographyRegionsIndex);
mirrorPublicPackAsset('global-places.json', globalPlacesIndex);
mirrorPublicPackAsset('geo-spatial-index.json', spatialIndex);
console.log(`Prepared Natural Earth boundaries with ${boundaries.contents.points} points at ${boundariesPath}`);
console.log(`Prepared Natural Earth populated places with ${populatedPlaces.length} places at ${populatedPlacesPath}`);
console.log(`Prepared Natural Earth geography regions with ${geographyRegions.length} places at ${geographyRegionsPath}`);
console.log(`Prepared GeoNames cities with ${geonamesCities.length} cities`);
console.log(`Prepared global places index with ${globalPlaces.length} features at ${globalPlacesPath}`);
console.log(`Prepared spatial grid index with ${spatialIndex.contents.cells} cells at ${spatialIndexPath}`);
console.log(`Prepared offline geo manifest at ${outputPath}`);

function naturalEarthDataset(preferredName, fallbackName) {
  const preferredPath = resolve(naturalEarthDir, `${preferredName}.zip`);
  try {
    statSync(preferredPath);
    return { name: preferredName, zipPath: preferredPath };
  } catch {
    if (!fallbackName) {
      throw new Error(`Missing Natural Earth source ${preferredName}.zip`);
    }
  }
  const fallbackPath = resolve(naturalEarthDir, `${fallbackName}.zip`);
  statSync(fallbackPath);
  return { name: fallbackName, zipPath: fallbackPath };
}

function naturalEarthUrl(dataset) {
  const scale = dataset.name.match(/ne_(\d+)m_/)?.[1] ?? '110';
  const category = dataset.name.includes('coastline') || dataset.name.includes('land') || dataset.name.includes('geography')
    ? 'physical'
    : 'cultural';
  return `https://naturalearth.s3.amazonaws.com/${scale}m_${category}/${dataset.name}.zip`;
}

function relativePathForDataset(dataset) {
  return `shared/source-data/natural-earth/${dataset.name}.zip`;
}

function geonamesSource(name) {
  const zipPath = resolve(geonamesDir, `${name}.zip`);
  statSync(zipPath);
  return { name, zipPath };
}

function relativePathForGeoNames(dataset) {
  return `shared/source-data/geonames/${dataset.name}.zip`;
}

function fileEntry(relativePath) {
  const absolutePath = resolve(root, relativePath);
  const data = readFileSync(absolutePath);
  return {
    path: relativePath,
    bytes: statSync(absolutePath).size,
    sha256: createHash('sha256').update(data).digest('hex')
  };
}

function generatedJsonEntry(relativePath, value) {
  const data = Buffer.from(`${JSON.stringify(value)}\n`);
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

function readGeoNamesCities(text) {
  return text
    .trim()
    .split('\n')
    .map((line) => line.split('\t'))
    .map((fields) => ({
      id: `geonames-city-${fields[0]}`,
      geonameId: numberField(fields[0]),
      name: fields[1],
      asciiName: fields[2],
      alternateNames: fields[3],
      latitude: numberField(fields[4], Number.NaN),
      longitude: numberField(fields[5], Number.NaN),
      featureClass: fields[6],
      featureCode: fields[7],
      countryCode: fields[8],
      admin1: fields[10],
      population: numberField(fields[14]),
      elevationMeters: numberField(fields[15], Number.NaN),
      timezone: fields[17]
    }))
    .filter((city) =>
      city.name &&
      Number.isFinite(city.latitude) &&
      Number.isFinite(city.longitude) &&
      city.population >= 15_000
    )
    .sort((left, right) =>
      right.population - left.population ||
      left.countryCode.localeCompare(right.countryCode) ||
      left.name.localeCompare(right.name)
    );
}

function readZipEntry(zipPath, entryName) {
  return execFileSync('unzip', ['-p', zipPath, entryName], { maxBuffer: 80 * 1024 * 1024 });
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

function readGeographyRegions(buffer) {
  const records = readDbfRecords(buffer);
  return records
    .map((record, index) => ({
      id: `natural-earth-region-${numberField(record.ne_id ?? record.NE_ID, index)}`,
      name: stringField(record.name_en) || stringField(record.name) || stringField(record.label),
      nameZh: stringField(record.name_zht) || stringField(record.name_zh),
      label: stringField(record.label),
      type: 'landmark',
      featureClass: stringField(record.featurecla),
      region: stringField(record.region),
      subregion: stringField(record.subregion),
      latitude: numberField(record.lat_y ?? record.LAT_Y),
      longitude: numberField(record.long_x ?? record.LONG_X),
      scalerank: numberField(record.scalerank, 99),
      minZoom: numberField(record.min_zoom, 9)
    }))
    .filter((region) =>
      region.name &&
      Number.isFinite(region.latitude) &&
      Number.isFinite(region.longitude)
    )
    .sort((a, b) =>
      a.scalerank - b.scalerank ||
      a.minZoom - b.minZoom ||
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

function normalizeFixtureLandmark(landmark) {
  return {
    id: landmark.id,
    name: landmark.name,
    nameZh: landmark.nameZh,
    type: landmark.type,
    latitude: roundCoordinate(landmark.latitude),
    longitude: roundCoordinate(landmark.longitude),
    countryCode: landmark.countryCode,
    admin1: landmark.admin1,
    population: landmark.population,
    importance: landmark.importance ?? 0.9,
    minZoomRank: landmark.minZoomRank ?? 4,
    tourismHint: landmark.tourismHint,
    source: 'project-fixture'
  };
}

function normalizeNaturalEarthPlace(place) {
  return {
    id: place.id,
    name: place.name,
    nameZh: place.nameZh,
    type: 'majorCity',
    latitude: roundCoordinate(place.latitude),
    longitude: roundCoordinate(place.longitude),
    countryCode: place.countryCode,
    admin1: place.admin1,
    population: place.population,
    importance: importanceForNaturalEarthPlace(place),
    minZoomRank: Math.max(0, Math.round(place.minZoom)),
    tourismHint: place.isCapital ? '首都' : undefined,
    source: 'natural-earth-populated-places'
  };
}

function normalizeNaturalEarthRegion(region) {
  return {
    id: region.id,
    name: region.name,
    nameZh: region.nameZh,
    type: 'landmark',
    latitude: roundCoordinate(region.latitude),
    longitude: roundCoordinate(region.longitude),
    importance: Math.max(0.78, 1 - Math.min(8, region.scalerank) * 0.035),
    minZoomRank: Math.max(0, Math.round(region.minZoom)),
    tourismHint: region.subregion || region.region,
    source: 'natural-earth-geography-regions'
  };
}

function normalizeGeoNamesCity(city) {
  return {
    id: city.id,
    name: city.name,
    type: 'majorCity',
    latitude: roundCoordinate(city.latitude),
    longitude: roundCoordinate(city.longitude),
    countryCode: city.countryCode,
    admin1: city.admin1,
    population: city.population,
    importance: importanceForGeoNamesCity(city),
    minZoomRank: minZoomForGeoNamesCity(city),
    tourismHint: city.featureCode === 'PPLC' ? '首都' : undefined,
    source: 'geonames-cities15000'
  };
}

function importanceForNaturalEarthPlace(place) {
  if (place.isWorldCity || place.isMegaCity || place.isCapital) {
    return 0.96;
  }
  if ((place.population ?? 0) >= 3_000_000) {
    return 0.92;
  }
  if (place.labelRank <= 3 || place.scalerank <= 3) {
    return 0.88;
  }
  return 0.78;
}

function importanceForGeoNamesCity(city) {
  if (city.featureCode === 'PPLC') {
    return 0.94;
  }
  if (city.population >= 3_000_000) {
    return 0.9;
  }
  if (city.population >= 1_000_000) {
    return 0.86;
  }
  if (city.population >= 250_000) {
    return 0.8;
  }
  return 0.72;
}

function minZoomForGeoNamesCity(city) {
  if (city.population >= 3_000_000 || city.featureCode === 'PPLC') {
    return 3;
  }
  if (city.population >= 1_000_000) {
    return 4;
  }
  if (city.population >= 250_000) {
    return 6;
  }
  return 8;
}

function mergeGlobalPlaces(features) {
  const seen = new Set();
  const merged = [];
  for (const feature of features) {
    if (!feature.id || !feature.name || !Number.isFinite(feature.latitude) || !Number.isFinite(feature.longitude)) {
      continue;
    }
    const key = [
      feature.countryCode ?? '',
      (feature.nameZh ?? feature.name).toLowerCase(),
      feature.latitude.toFixed(2),
      feature.longitude.toFixed(2)
    ].join('|');
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    merged.push(feature);
  }
  return merged.sort((left, right) =>
    right.importance - left.importance ||
    (right.population ?? 0) - (left.population ?? 0) ||
    left.name.localeCompare(right.name)
  );
}

function buildSpatialIndex(features, boundaryLines) {
  const cellDegrees = 5;
  const cells = new Map();
  const addToCell = (key, kind, id) => {
    const cell = cells.get(key) ?? { features: [], boundaryLines: [] };
    cell[kind].push(id);
    cells.set(key, cell);
  };

  for (const feature of features) {
    addToCell(cellKey(feature.latitude, feature.longitude, cellDegrees), 'features', feature.id);
  }

  boundaryLines.forEach((line, index) => {
    const bbox = bboxForCoordinates(line.coordinates);
    for (const key of cellKeysForBbox(bbox, cellDegrees)) {
      addToCell(key, 'boundaryLines', `${line.kind}-${index}`);
    }
  });

  const normalizedCells = Object.fromEntries(
    [...cells.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, value]) => [
        key,
        {
          features: [...new Set(value.features)].sort(),
          boundaryLines: [...new Set(value.boundaryLines)].sort()
        }
      ])
  );

  return {
    schemaVersion: '1.0.0',
    generatedAt: new Date().toISOString(),
    cellDegrees,
    sourceIndexes: {
      places: 'shared/offline-packs/core-global/global-places.json',
      boundaries: 'shared/offline-packs/core-global/geo-boundaries.json'
    },
    contents: {
      cells: Object.keys(normalizedCells).length,
      indexedFeatures: features.length,
      indexedBoundaryLines: boundaryLines.length
    },
    cells: normalizedCells
  };
}

function cellKey(latitude, longitude, cellDegrees) {
  const latCell = Math.max(0, Math.min(35, Math.floor((latitude + 90) / cellDegrees)));
  const lonCell = Math.max(0, Math.min(71, Math.floor((longitude + 180) / cellDegrees)));
  return `${latCell}:${lonCell}`;
}

function cellKeysForBbox(bbox, cellDegrees) {
  const minLat = Math.max(-90, bbox.minLat);
  const maxLat = Math.min(90, bbox.maxLat);
  const minLon = Math.max(-180, bbox.minLon);
  const maxLon = Math.min(180, bbox.maxLon);
  const keys = [];
  for (let lat = Math.floor((minLat + 90) / cellDegrees); lat <= Math.floor((maxLat + 90) / cellDegrees); lat += 1) {
    for (let lon = Math.floor((minLon + 180) / cellDegrees); lon <= Math.floor((maxLon + 180) / cellDegrees); lon += 1) {
      keys.push(`${Math.max(0, Math.min(35, lat))}:${Math.max(0, Math.min(71, lon))}`);
    }
  }
  return [...new Set(keys)];
}

function bboxForCoordinates(coordinates) {
  return coordinates.reduce(
    (bbox, [latitude, longitude]) => ({
      minLat: Math.min(bbox.minLat, latitude),
      maxLat: Math.max(bbox.maxLat, latitude),
      minLon: Math.min(bbox.minLon, longitude),
      maxLon: Math.max(bbox.maxLon, longitude)
    }),
    { minLat: 90, maxLat: -90, minLon: 180, maxLon: -180 }
  );
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
