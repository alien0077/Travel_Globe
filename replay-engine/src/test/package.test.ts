import { describe, expect, it } from 'vitest';
import { assertJourney } from '../data/validateJourney';
import { sampleJourney } from '../data/sampleJourney';
import { createTravelGlobePackage, readTravelGlobePackage } from '../export/travelglobePackage';
import { createShareSafeJourney } from '../privacy/redactJourney';

describe('portable journey package', () => {
  it('exports and reads a stored .travelglobe package', async () => {
    const blob = createTravelGlobePackage(sampleJourney);
    expect(blob.type).toBe('application/zip');
    expect(blob.size).toBeGreaterThan(1000);

    const parsed = await readTravelGlobePackage(blob);
    assertJourney(parsed);
    expect(parsed.id).toBe(sampleJourney.id);
  });

  it('creates a share-safe copy without mutating the original journey', () => {
    const shareSafe = createShareSafeJourney(sampleJourney);
    const originalFirst = sampleJourney.segments[0].rawRoute.points[0];
    const redactedFirst = shareSafe.segments[0].rawRoute.points[0];

    expect(shareSafe.id).toBe(sampleJourney.id);
    expect(shareSafe.media).toEqual([]);
    expect(redactedFirst.latitude).not.toBe(originalFirst.latitude);
    expect(sampleJourney.title).not.toContain('share-safe');
  });
});
