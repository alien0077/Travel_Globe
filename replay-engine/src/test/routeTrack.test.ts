import * as THREE from 'three';
import { describe, expect, it } from 'vitest';
import type { LocationPoint } from '../data/types';
import { createRouteTrack, splitRouteByAltitudePhase, updateRouteTrack } from '../route/createRouteLine';

describe('route track rendering', () => {
  const route = makeRoute([0, 5200, 11_500, 11_700, 6200, 0]);

  it('separates climb and descent sections from altitude changes', () => {
    const phases = splitRouteByAltitudePhase(route);

    expect(phases.climb.length).toBeGreaterThanOrEqual(3);
    expect(phases.descent.length).toBeGreaterThanOrEqual(3);
    expect(phases.climb[0].altitudeMeters).toBe(0);
    expect(phases.descent[phases.descent.length - 1].altitudeMeters).toBe(0);
  });

  it('updates flown and remaining line geometry independently', () => {
    const track = createRouteTrack(route, route.slice(0, 2));
    expect(positionCount(track.userData.routeTrack.flown)).toBeGreaterThan(2);
    expect(positionCount(track.userData.routeTrack.remaining)).toBeGreaterThan(5);

    updateRouteTrack(track, route, route.slice(0, 4));

    expect(positionCount(track.userData.routeTrack.flown)).toBeGreaterThan(4);
    expect(positionCount(track.userData.routeTrack.remaining)).toBeGreaterThan(3);
    expect(track.userData.routeTrack.climb.children.length).toBe(1);
    expect(track.userData.routeTrack.descent.children.length).toBe(1);
  });
});

function makeRoute(altitudes: number[]): LocationPoint[] {
  const startMs = Date.parse('2026-07-13T00:00:00Z');
  return altitudes.map((altitudeMeters, index) => ({
    id: `point-${index}`,
    journeyId: 'journey',
    segmentId: 'segment',
    timestamp: new Date(startMs + index * 600_000).toISOString(),
    latitude: 24 + index * 0.8,
    longitude: 121 + index * 1.2,
    altitudeMeters,
    speedMetersPerSecond: 220,
    source: 'estimated'
  }));
}

function positionCount(line: THREE.Line): number {
  return line.geometry.getAttribute('position').count;
}
