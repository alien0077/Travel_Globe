import { describe, expect, it } from 'vitest';
import { sampleJourney } from '../data/sampleJourney';
import { createGpx, createKml } from '../export/geoExport';

describe('geographic exports', () => {
  it('exports GPX with track points and detected waypoints', () => {
    const gpx = createGpx(sampleJourney);

    expect(gpx).toContain('<gpx version="1.1"');
    expect(gpx).toContain('<trkpt');
    expect(gpx).toContain('<wpt');
    expect(gpx).toContain('Taipei to Tokyo Flight');
  });

  it('exports KML with planned and actual overlays', () => {
    const kml = createKml(sampleJourney);

    expect(kml).toContain('<kml');
    expect(kml).toContain('Flight Plan');
    expect(kml).toContain('Actual Track');
    expect(kml).toContain('Top of Descent');
  });
});
