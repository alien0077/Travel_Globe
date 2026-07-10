import { describe, expect, it } from 'vitest';
import { sampleJourney } from '../data/sampleJourney';
import { getPrimaryFlightSegment } from '../data/types';
import { getRouteTimeBounds, sampleReplayAt } from '../replay/buildReplayFrames';

describe('replay sampling', () => {
  const segment = getPrimaryFlightSegment(sampleJourney);
  const bounds = getRouteTimeBounds(segment);

  it('derives a positive replay duration and distance', () => {
    expect(bounds.durationSeconds).toBeGreaterThan(10_000);
    expect(bounds.totalDistanceMeters).toBeGreaterThan(2_000_000);
  });

  it('samples the beginning and end of the flight', () => {
    const start = sampleReplayAt(segment, 0);
    const end = sampleReplayAt(segment, bounds.durationSeconds);

    expect(start.point.latitude).toBeCloseTo(segment.origin.latitude, 3);
    expect(start.point.longitude).toBeCloseTo(segment.origin.longitude, 3);
    expect(end.point.latitude).toBeCloseTo(segment.destination.latitude, 3);
    expect(end.point.longitude).toBeCloseTo(segment.destination.longitude, 3);
    expect(end.remainingDistanceMeters).toBeLessThan(1);
  });
});
