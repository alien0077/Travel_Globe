import { describe, expect, it } from 'vitest';
import { sampleJourney } from '../data/sampleJourney';
import { getPrimaryFlightSegment } from '../data/types';
import {
  buildFlightHudMetrics,
  buildFlightOverlay,
  getActualRouteThrough,
  summarizeBelowMe
} from '../flight/flightAnalytics';
import { getRouteTimeBounds, sampleReplayAt } from '../replay/buildReplayFrames';

describe('flight overlay analytics', () => {
  const segment = getPrimaryFlightSegment(sampleJourney);
  const bounds = getRouteTimeBounds(segment);

  it('detects replay events and flight metrics from the route', () => {
    const overlay = buildFlightOverlay(sampleJourney, segment);

    expect(overlay.flightNumber).toBe('CI100');
    expect(overlay.aircraftType).toContain('A380');
    expect(overlay.totalDistanceMeters).toBeGreaterThan(2_000_000);
    expect(overlay.maxAltitudeMeters).toBeGreaterThan(11_000);
    expect(overlay.events.map((event) => event.kind)).toEqual(
      expect.arrayContaining(['takeoff', 'topOfClimb', 'topOfDescent', 'landing', 'maxAltitude', 'maxSpeed'])
    );
  });

  it('does not inject a default aircraft type when metadata is missing', () => {
    const overlay = buildFlightOverlay(sampleJourney, {
      ...segment,
      metadata: {
        flightNumber: 'CI100'
      }
    });

    expect(overlay.aircraftType).toBe('');
  });

  it('formats HUD values for in-flight replay', () => {
    const sample = sampleReplayAt(segment, bounds.durationSeconds * 0.55);
    const metrics = buildFlightHudMetrics(sampleJourney, segment, sample, bounds.durationSeconds * 0.55);

    expect(metrics.flightNumber).toBe('CI100');
    expect(metrics.routeLabel).toBe('TPE -> HND');
    expect(metrics.altitudeFeet).toContain('ft');
    expect(metrics.speedKmh).toContain('km/h');
    expect(metrics.headingDegrees).toContain('deg');
    expect(metrics.distanceLabel).toContain('/');
    expect(metrics.remainingDistanceLabel).toContain('km');
    expect(metrics.verticalSpeedLabel).toMatch(/上升|巡航|下降/);
  });

  it('builds a continuous actual route through the current replay time', () => {
    const route = getActualRouteThrough(segment, bounds.durationSeconds * 0.5);

    expect(route.length).toBeGreaterThan(2);
    expect(route[route.length - 1].id).toContain('runtime');
  });

  it('summarizes what is below and nearby', () => {
    const sample = sampleReplayAt(segment, bounds.durationSeconds * 0.8);
    const summary = summarizeBelowMe(sample.point, sample.bearingDegrees);

    expect(summary.belowLabel.length).toBeGreaterThan(0);
    expect(summary.nearby.length).toBeGreaterThanOrEqual(3);
    expect(summary.windowHint).toMatch(/在你的/);
  });
});
