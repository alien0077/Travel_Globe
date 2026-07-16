import { describe, expect, it } from 'vitest';
import { simulatedCloudCoverFraction } from '../weather/simulatedCloudCover';

describe('simulated weather overlays', () => {
  it('produces bounded cloud cover that varies by route point and time', () => {
    const taiwanMorning = simulatedCloudCoverFraction(
      { latitude: 22.57, longitude: 120.35 },
      '2026-07-14T00:00:00.000Z'
    );
    const japanEvening = simulatedCloudCoverFraction(
      { latitude: 35.77, longitude: 140.38 },
      '2026-07-16T12:00:00.000Z'
    );

    expect(taiwanMorning).toBeGreaterThanOrEqual(0.12);
    expect(taiwanMorning).toBeLessThanOrEqual(0.88);
    expect(japanEvening).toBeGreaterThanOrEqual(0.12);
    expect(japanEvening).toBeLessThanOrEqual(0.88);
    expect(Math.abs(taiwanMorning - japanEvening)).toBeGreaterThan(0.02);
  });
});
