import { beforeAll, describe, expect, it } from 'vitest';
import globalPlacesIndex from '../../../shared/offline-packs/core-global/global-places.json';
import spatialIndex from '../../../shared/offline-packs/core-global/geo-spatial-index.json';
import { sampleJourney } from '../data/sampleJourney';
import { getPrimaryFlightSegment } from '../data/types';
import { installLandmarkIndex } from '../geo/landmarks';
import {
  buildFlightHudMetrics,
  buildFlightOverlay,
  getActualRouteThrough,
  landmarksForSegment,
  summarizeBelowMe
} from '../flight/flightAnalytics';
import { buildPreloadedFlightJourney } from '../flight-preload/buildPreloadedFlightJourney';
import { getRouteTimeBounds, sampleReplayAt } from '../replay/buildReplayFrames';

describe('flight overlay analytics', () => {
  const segment = getPrimaryFlightSegment(sampleJourney);
  const bounds = getRouteTimeBounds(segment);

  beforeAll(() => {
    installLandmarkIndex(globalPlacesIndex.features, spatialIndex);
  });

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

  it('defaults to A320 when aircraft metadata is missing', () => {
    const overlay = buildFlightOverlay(sampleJourney, {
      ...segment,
      metadata: {
        flightNumber: 'CI100'
      }
    });

    expect(overlay.aircraftType).toBe('A320');
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

  it('filters landmark guidance to the active flight corridor', () => {
    const preloaded = buildPreloadedFlightJourney({
      flightNumber: 'XX901',
      originIata: 'AAL',
      destinationIata: 'PTD',
      departureDate: '2026-07-14',
      departureTime: '09:30',
      durationMinutes: 480
    });
    const routeSegment = getPrimaryFlightSegment(preloaded.journey);
    const routeLandmarks = landmarksForSegment(routeSegment);
    const names = routeLandmarks.map((feature) => feature.nameZh ?? feature.name);

    expect(routeLandmarks.length).toBeGreaterThan(0);
    expect(names).not.toEqual(expect.arrayContaining(['東京', '台北101', '上海']));
  });

  it('uses OpenFlights equipment codes only as an aircraft fallback when available', () => {
    const preloaded = buildPreloadedFlightJourney({
      flightNumber: 'CI100',
      originIata: 'TPE',
      destinationIata: 'NRT',
      departureDate: '2026-07-14',
      departureTime: '09:30'
    });
    const routeSegment = getPrimaryFlightSegment(preloaded.journey);

    expect(routeSegment.metadata.routeFallbackSource).toBe('great-circle');
    expect(routeSegment.metadata.aircraftTypeSource).toBe('openflights-route-graph');
    expect(routeSegment.metadata.aircraftType).toBe('744');
    expect(routeSegment.metadata.openFlightsRouteCount).toBeGreaterThan(0);
    expect(preloaded.warnings[0]).toContain('僅用其 equipment code 補機型 744');
  });

  it('keeps aviationstack aircraft data ahead of OpenFlights equipment codes', () => {
    const preloaded = buildPreloadedFlightJourney({
      flightNumber: 'CI100',
      originIata: 'TPE',
      destinationIata: 'NRT',
      departureDate: '2026-07-14',
      departureTime: '09:30',
      aircraftType: 'A350',
      source: 'aviationstack'
    });
    const routeSegment = getPrimaryFlightSegment(preloaded.journey);

    expect(routeSegment.metadata.routeFallbackSource).toBe('great-circle');
    expect(routeSegment.metadata.aircraftTypeSource).toBe('aviationstack');
    expect(routeSegment.metadata.aircraftType).toBe('A350');
    expect(routeSegment.metadata.openFlightsAircraftTypes).toContain('744');
  });
});
