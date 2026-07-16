import { describe, expect, it } from 'vitest';
import boundariesIndex from '../../../shared/offline-packs/core-global/geo-boundaries.json';
import globalPlacesIndex from '../../../shared/offline-packs/core-global/global-places.json';
import geoManifest from '../../../shared/offline-packs/core-global/manifest.json';
import spatialIndex from '../../../shared/offline-packs/core-global/geo-spatial-index.json';
import ourAirportsManifest from '../../../shared/offline-packs/core-global/ourairports-manifest.json';

describe('offline data indexes', () => {
  it('prepares Natural Earth boundary lines for globe rendering', () => {
    expect(geoManifest.contents.countryBorders.status).toBe('prepared');
    expect(boundariesIndex.contents.coastlines).toBeGreaterThan(100);
    expect(boundariesIndex.contents.countryBorders).toBeGreaterThan(100);
    expect(boundariesIndex.contents.points).toBeGreaterThan(5_000);
  });

  it('tracks generated OurAirports indexes in a source manifest', () => {
    expect(ourAirportsManifest.indexes.airports.records).toBeGreaterThan(4_000);
    expect(ourAirportsManifest.indexes.aviationContext.frequencies).toBeGreaterThan(10_000);
    expect(ourAirportsManifest.indexes.aviationContext.navaids).toBeGreaterThan(5_000);
  });

  it('installs GeoNames global places and a spatial grid index', () => {
    expect(geoManifest.contents.geonamesCities).toBeGreaterThan(30_000);
    expect(geoManifest.contents.globalPlaces).toBeGreaterThan(40_000);
    expect(geoManifest.contents.spatialIndex.status).toBe('prepared-grid');
    expect(globalPlacesIndex.contents.features).toBe(geoManifest.contents.globalPlaces);
    expect(spatialIndex.contents.cells).toBeGreaterThan(1_000);
    expect(geoManifest.payloads.coreGlobalAtlas.some((payload) =>
      payload.path.endsWith('global-places.json')
    )).toBe(true);
  });
});
