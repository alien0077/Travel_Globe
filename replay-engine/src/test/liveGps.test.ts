import { describe, expect, it } from 'vitest';
import { sampleJourney } from '../data/sampleJourney';
import { getPrimaryFlightSegment } from '../data/types';
import { haversineDistanceMeters, initialBearingDegrees } from '../geo/geodesy';
import { LiveGpsTracker, liveGpsPointFromNativeMessage } from '../live/liveGps';
import {
  completeJourneyFromRecording,
  createJourneyFromNativeRecording
} from '../live/completeJourneyFromRecording';

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

  it('turns completed native GPS recording into a completed journey without estimated points', () => {
    const completed = completeJourneyFromRecording(sampleJourney, {
      nativeJourneyId: 'native-1',
      webJourneyId: sampleJourney.id,
      segmentId: segment.id,
      flightNumber: 'FD235',
      originIata: 'NRT',
      destinationIata: 'KHH',
      aircraftType: 'A320',
      status: 'completed',
      startedAt: '2026-07-14T12:00:00.000Z',
      endedAt: '2026-07-14T12:00:10.000Z',
      points: [
        {
          timestamp: '2026-07-14T12:00:00.000Z',
          latitude: 35.77,
          longitude: 140.38,
          altitudeMeters: 300,
          speedMetersPerSecond: 90,
          courseDegrees: 220,
          horizontalAccuracyMeters: 20,
          verticalAccuracyMeters: 25,
          source: 'gps'
        },
        {
          timestamp: '2026-07-14T12:00:10.000Z',
          latitude: 35.6,
          longitude: 140.1,
          altitudeMeters: 1800,
          speedMetersPerSecond: 160,
          courseDegrees: 222,
          horizontalAccuracyMeters: 20,
          verticalAccuracyMeters: 25,
          source: 'gps'
        }
      ]
    });

    const completedSegment = getPrimaryFlightSegment(completed);

    expect(completed.status).toBe('completed');
    expect(completed.metadata.nativeJourneyId).toBe('native-1');
    expect(completedSegment.derivedReplayRoute.points).toHaveLength(2);
    expect(completedSegment.derivedReplayRoute.points.every((point) => point.source === 'gps')).toBe(true);
    expect(completed.events.some((event) => event.id === `event-${segment.id}-gps-stop`)).toBe(true);
  });

  it('creates a standalone replay journey from a GPS-only native recording', () => {
    const journey = createJourneyFromNativeRecording({
      nativeJourneyId: 'gps-only-1',
      status: 'completed',
      startedAt: '2026-07-14T12:00:00.000Z',
      endedAt: '2026-07-14T12:00:10.000Z',
      points: [
        {
          timestamp: '2026-07-14T12:00:00.000Z',
          latitude: 35.77,
          longitude: 140.38,
          altitudeMeters: 300,
          speedMetersPerSecond: 90,
          courseDegrees: 220,
          horizontalAccuracyMeters: 20,
          verticalAccuracyMeters: 25,
          source: 'gps'
        },
        {
          timestamp: '2026-07-14T12:00:10.000Z',
          latitude: 35.6,
          longitude: 140.1,
          altitudeMeters: 1800,
          speedMetersPerSecond: 160,
          courseDegrees: 222,
          horizontalAccuracyMeters: 20,
          verticalAccuracyMeters: 25,
          source: 'gps'
        }
      ]
    });

    expect(journey?.id).toBe('native-gps-only-1');
    expect(journey?.title).toBe('GPS Recording 2026-07-14');
    expect(journey?.segments[0].id).toBe('segment-gps-only-1');
    expect(journey?.segments[0].derivedReplayRoute.points).toHaveLength(2);
    expect(journey?.segments[0].events).toEqual([
      'event-segment-gps-only-1-gps-start',
      'event-segment-gps-only-1-gps-stop'
    ]);
  });

  it('keeps a one-point GPS-only native recording as a replayable journey', () => {
    const journey = createJourneyFromNativeRecording({
      nativeJourneyId: 'gps-one-point',
      status: 'completed',
      startedAt: '2026-07-14T12:00:00.000Z',
      endedAt: '2026-07-14T12:00:30.000Z',
      points: [
        {
          timestamp: '2026-07-14T12:00:00.000Z',
          latitude: 35.77,
          longitude: 140.38,
          altitudeMeters: 300,
          speedMetersPerSecond: 0,
          courseDegrees: 220,
          horizontalAccuracyMeters: 20,
          verticalAccuracyMeters: 25,
          source: 'gps'
        }
      ]
    });

    const points = journey?.segments[0].derivedReplayRoute.points ?? [];

    expect(journey?.statistics?.gpsPointCount).toBe(1);
    expect(journey?.metadata.replayRouteSynthetic).toBe(true);
    expect(points).toHaveLength(2);
    expect(points[0].source).toBe('gps');
    expect(points[1].source).toBe('estimated');
  });

  it('uses an airport anchor for a zero-point native recording with flight metadata', () => {
    const journey = createJourneyFromNativeRecording({
      nativeJourneyId: 'gps-zero-point',
      status: 'completed',
      flightNumber: 'FD235',
      originIata: 'NRT',
      destinationIata: 'KHH',
      startedAt: '2026-07-14T12:00:00.000Z',
      endedAt: '2026-07-14T12:05:00.000Z',
      points: []
    });

    const points = journey?.segments[0].derivedReplayRoute.points ?? [];

    expect(journey?.statistics?.gpsPointCount).toBe(0);
    expect(journey?.metadata.replayRouteSynthetic).toBe(true);
    expect(journey?.segments[0].origin.iataCode).toBe('NRT');
    expect(points).toHaveLength(2);
    expect(points.every((point) => point.source === 'estimated')).toBe(true);
  });
});
