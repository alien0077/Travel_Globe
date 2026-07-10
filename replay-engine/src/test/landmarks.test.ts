import { describe, expect, it } from 'vitest';
import { findNearestLandmark, relativeWindowDirection } from '../geo/landmarks';

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
});
