import { describe, expect, it } from 'vitest';
import boundariesIndex from '../../../shared/offline-packs/core-global/geo-boundaries.json';
import geoManifest from '../../../shared/offline-packs/core-global/manifest.json';
import ourAirportsManifest from '../../../shared/offline-packs/core-global/ourairports-manifest.json';

describe('offline data indexes', () => {
  it('prepares Natural Earth boundary lines for globe rendering', () => {
    expect(geoManifest.contents.countryBorders.status).toBe('prepared');
    expect(boundariesIndex.contents.coastlines).toBeGreaterThan(100);
    expect(boundariesIndex.contents.countryBorders).toBeGreaterThan(100);
    expect(boundariesIndex.contents.points).toBeGreaterThan(5_000);
  });

  it('tracks generated OurAirports indexes in a source manifest', () => {
    expect(ourAirportsManifest.indexes.airports.records).toBeGreaterThan(7_000);
    expect(ourAirportsManifest.indexes.aviationContext.frequencies).toBeGreaterThan(18_000);
    expect(ourAirportsManifest.indexes.aviationContext.navaids).toBeGreaterThan(5_000);
  });
});
