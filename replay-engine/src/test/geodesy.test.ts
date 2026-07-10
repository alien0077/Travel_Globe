import { describe, expect, it } from 'vitest';
import {
  haversineDistanceMeters,
  initialBearingDegrees,
  interpolateGreatCircle
} from '../geo/geodesy';

const taipei = { latitude: 25.0797, longitude: 121.2342 };
const haneda = { latitude: 35.5494, longitude: 139.7798 };

describe('geodesy', () => {
  it('calculates distance between Taoyuan and Haneda within expected flight range', () => {
    const distance = haversineDistanceMeters(taipei, haneda);
    expect(distance).toBeGreaterThan(2_050_000);
    expect(distance).toBeLessThan(2_200_000);
  });

  it('calculates an initial northeast bearing from Taoyuan to Haneda', () => {
    const bearing = initialBearingDegrees(taipei, haneda);
    expect(bearing).toBeGreaterThan(45);
    expect(bearing).toBeLessThan(60);
  });

  it('interpolates along the great-circle path', () => {
    const midpoint = interpolateGreatCircle(taipei, haneda, 0.5);
    expect(midpoint.latitude).toBeGreaterThan(29);
    expect(midpoint.latitude).toBeLessThan(32);
    expect(midpoint.longitude).toBeGreaterThan(129);
    expect(midpoint.longitude).toBeLessThan(132);
  });
});
