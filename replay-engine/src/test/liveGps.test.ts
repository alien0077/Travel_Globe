import { describe, expect, it } from 'vitest';
import { sampleJourney } from '../data/sampleJourney';
import { getPrimaryFlightSegment } from '../data/types';
import { haversineDistanceMeters, initialBearingDegrees } from '../geo/geodesy';
import { LiveGpsTracker, liveGpsPointFromNativeMessage } from '../live/liveGps';

describe('live GPS native bridge', () => {
  const segment = getPrimaryFlightSegment(sampleJourney);

  it('converts native location.update payload into a GPS point', () => {
    const point = liveGpsPointFromNativeMessage(
      {
        type: 'location.update',
        payload: JSON.stringify({
          timestamp: '2026-07-14T12:00:00.000Z',
          latitude: 22.5771,
          longitude: 120.3502,
          altitudeMeters: 1200,
          speedMetersPerSecond: 230,
          courseDegrees: 42,
          horizontalAccuracyMeters: 24,
          verticalAccuracyMeters: 30,
          source: 'gps'
        })
      },
      'journey-live',
      'segment-live'
    );

    expect(point?.source).toBe('gps');
    expect(point?.journeyId).toBe('journey-live');
    expect(point?.segmentId).toBe('segment-live');
    expect(point?.courseDegrees).toBe(42);
  });

  it('falls back to bearing between consecutive GPS points when course is unavailable', () => {
    const tracker = new LiveGpsTracker();
    const first = liveGpsPointFromNativeMessage(
      {
        type: 'location.update',
        payload: {
          timestamp: '2026-07-14T12:00:00.000Z',
          latitude: 22.5771,
          longitude: 120.3502,
          altitudeMeters: 900,
          speedMetersPerSecond: 220,
          courseDegrees: null,
          horizontalAccuracyMeters: 20,
          verticalAccuracyMeters: 25,
          source: 'gps'
        }
      },
      'journey-live',
      'segment-live'
    );
    const second = liveGpsPointFromNativeMessage(
      {
        type: 'location.update',
        payload: {
          timestamp: '2026-07-14T12:00:05.000Z',
          latitude: 22.685,
          longitude: 120.49,
          altitudeMeters: 1600,
          speedMetersPerSecond: 230,
          courseDegrees: null,
          horizontalAccuracyMeters: 20,
          verticalAccuracyMeters: 25,
          source: 'gps'
        }
      },
      'journey-live',
      'segment-live'
    );
    expect(first).toBeDefined();
    expect(second).toBeDefined();
    tracker.ingest(first!, 0);
    tracker.ingest(second!, 5_000);

    const sample = tracker.sample(5_500, segment);

    expect(sample?.bearingDegrees).toBeCloseTo(initialBearingDegrees(first!, second!), 3);
    expect(sample?.status).toBe('live');
  });

  it('dead reckons short GPS gaps and stops after 90 seconds', () => {
    const tracker = new LiveGpsTracker();
    const point = liveGpsPointFromNativeMessage(
      {
        type: 'location.update',
        payload: JSON.stringify({
          timestamp: '2026-07-14T12:00:00.000Z',
          latitude: 22.5771,
          longitude: 120.3502,
          altitudeMeters: 900,
          speedMetersPerSecond: 250,
          courseDegrees: 35,
          horizontalAccuracyMeters: 20,
          verticalAccuracyMeters: 25,
          source: 'gps'
        })
      },
      'journey-live',
      'segment-live'
    );
    expect(point).toBeDefined();
    tracker.ingest(point!, 0);

    const estimated = tracker.sample(30_000, segment);
    const lost = tracker.sample(120_000, segment);

    expect(estimated?.status).toBe('estimated');
    expect(estimated?.point.source).toBe('estimated');
    expect(haversineDistanceMeters(point!, estimated!.point)).toBeGreaterThan(7_000);
    expect(lost?.status).toBe('lost');
    expect(lost?.point.source).toBe('gps');
    expect(lost?.point.latitude).toBeCloseTo(point!.latitude, 6);
    expect(lost?.point.longitude).toBeCloseTo(point!.longitude, 6);
  });
});
