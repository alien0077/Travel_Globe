import { describe, expect, it } from 'vitest';
import { fixtureLandmarks, findNearestLandmark, landmarkWindowHint, relativeWindowDirection } from '../geo/landmarks';

describe('landmark proximity', () => {
  it('finds Mount Fuji near the Tokyo approach fixture', () => {
    const nearest = findNearestLandmark(
      { latitude: 34.9, longitude: 138.2, altitudeMeters: 5000 },
      55
    );

    expect(nearest?.feature.name).toBe('Mount Fuji');
    expect(nearest?.distanceMeters).toBeLessThan(100_000);
  });

  it('maps relative bearing to window guidance', () => {
    expect(relativeWindowDirection(0, 40)).toBe('right-front');
    expect(relativeWindowDirection(90, 0)).toBe('left side');
    expect(relativeWindowDirection(180, 180)).toBe('front');
  });

  it('ships enough offline landmark fixtures for in-flight labels', () => {
    expect(fixtureLandmarks.length).toBeGreaterThanOrEqual(40);
    expect(fixtureLandmarks.some((feature) => feature.nameZh === '富士山')).toBe(true);
    expect(fixtureLandmarks.some((feature) => feature.nameZh === '東京晴空塔')).toBe(true);
  });

  it('formats Traditional Chinese window guidance', () => {
    const nearest = findNearestLandmark(
      { latitude: 34.9, longitude: 138.2, altitudeMeters: 5000 },
      55
    );

    expect(nearest).toBeDefined();
    expect(landmarkWindowHint(nearest!)).toContain('富士山在你的');
  });
});
