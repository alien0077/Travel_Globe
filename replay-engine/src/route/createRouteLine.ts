import * as THREE from 'three';
import type { GeographicPoint, LocationPoint } from '../data/types';
import { geographicToVector3, haversineDistanceMeters, interpolateGreatCircle } from '../geo/geodesy';

export interface RouteLineOptions {
  color?: number;
  opacity?: number;
  altitudeScaleMeters?: number;
}

export type RouteTrack = THREE.Group & {
  userData: {
    routeTrack: {
      flown: THREE.Line;
      remaining: THREE.Line;
      climb: THREE.Group;
      descent: THREE.Group;
      altitudeScaleMeters: number;
    };
  };
};

export function createRouteLine(points: LocationPoint[], options: RouteLineOptions = {}): THREE.Line {
  const geometry = createRouteGeometry(points, options.altitudeScaleMeters);
  const material = new THREE.LineBasicMaterial({
    color: options.color ?? 0xf6d365,
    transparent: true,
    opacity: options.opacity ?? 0.96
  });

  return new THREE.Line(geometry, material);
}

export function updateRouteLine(line: THREE.Line, points: LocationPoint[], altitudeScaleMeters?: number): void {
  line.geometry.dispose();
  line.geometry = createRouteGeometry(points, altitudeScaleMeters);
}

export function createRouteTrack(
  fullRoute: LocationPoint[],
  flownRoute: LocationPoint[],
  altitudeScaleMeters = 620000
): RouteTrack {
  const track = new THREE.Group() as RouteTrack;
  const remaining = createRouteLine([], { color: 0x2f8a50, opacity: 0.46, altitudeScaleMeters });
  const flown = createRouteLine([], { color: 0x6cff8d, opacity: 0.98, altitudeScaleMeters });
  const climb = new THREE.Group();
  const descent = new THREE.Group();

  remaining.name = 'remaining route';
  flown.name = 'flown route';
  climb.name = 'climb route overlay';
  descent.name = 'descent route overlay';
  track.userData.routeTrack = { flown, remaining, climb, descent, altitudeScaleMeters };
  track.add(remaining, flown, climb, descent);
  updateRouteTrack(track, fullRoute, flownRoute, altitudeScaleMeters);
  return track;
}

export function updateRouteTrack(
  track: RouteTrack,
  fullRoute: LocationPoint[],
  flownRoute: LocationPoint[],
  altitudeScaleMeters = track.userData.routeTrack.altitudeScaleMeters
): void {
  const { flown, remaining, climb, descent } = track.userData.routeTrack;
  updateRouteLine(flown, flownRoute, altitudeScaleMeters);
  updateRouteLine(remaining, remainingRouteFrom(fullRoute, flownRoute), altitudeScaleMeters);

  const phases = splitRouteByAltitudePhase(fullRoute);
  updatePhaseGroup(climb, phases.climb, 0x62c8ff, 0.64, altitudeScaleMeters);
  updatePhaseGroup(descent, phases.descent, 0xffb35c, 0.72, altitudeScaleMeters);
  track.userData.routeTrack.altitudeScaleMeters = altitudeScaleMeters;
}

export function splitRouteByAltitudePhase(points: LocationPoint[]): { climb: LocationPoint[]; descent: LocationPoint[] } {
  if (points.length < 2) {
    return { climb: [], descent: [] };
  }

  const maxAltitudeMeters = Math.max(...points.map((point) => point.altitudeMeters ?? 0));
  const cruiseThresholdMeters = maxAltitudeMeters * 0.88;
  const topOfClimbIndex = Math.max(1, points.findIndex((point) => (point.altitudeMeters ?? 0) >= cruiseThresholdMeters));
  let lastCruiseIndex = topOfClimbIndex;
  for (let index = points.length - 1; index >= 0; index -= 1) {
    if ((points[index].altitudeMeters ?? 0) >= cruiseThresholdMeters) {
      lastCruiseIndex = index;
      break;
    }
  }
  const topOfDescentIndex = Math.max(topOfClimbIndex, lastCruiseIndex);

  return {
    climb: points.slice(0, topOfClimbIndex + 1),
    descent: points.slice(topOfDescentIndex)
  };
}

export function createRouteEventMarkers(
  points: GeographicPoint[],
  color = 0xffffff,
  altitudeScaleMeters = 620000
): THREE.Group {
  const group = new THREE.Group();
  const material = new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: 0.35,
    roughness: 0.4
  });

  for (const point of points) {
    const marker = new THREE.Mesh(new THREE.SphereGeometry(0.0035, 12, 8), material);
    const vector = geographicToVector3(point, 2, altitudeScaleMeters);
    marker.position.set(vector.x, vector.y, vector.z);
    group.add(marker);
  }

  return group;
}

function createRouteGeometry(points: LocationPoint[], altitudeScaleMeters = 700000): THREE.BufferGeometry {
  const positions: number[] = [];

  for (const point of createSmoothedRoutePoints(points)) {
    const vector = geographicToVector3(point, 2, altitudeScaleMeters);
    positions.push(vector.x, vector.y, vector.z);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}

function createSmoothedRoutePoints(points: LocationPoint[]): GeographicPoint[] {
  if (points.length < 2) {
    return points;
  }

  const maxAltitudeMeters = Math.max(...points.map((point) => point.altitudeMeters ?? 0));
  const totalDistance = Math.max(
    1,
    points.reduce((total, point, index) => index === 0 ? total : total + haversineDistanceMeters(points[index - 1], point), 0)
  );
  let distanceSoFar = 0;
  const smoothed: GeographicPoint[] = [];

  for (let index = 0; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    const segmentDistance = haversineDistanceMeters(current, next);
    const subdivisions = Math.max(4, Math.min(24, Math.ceil(segmentDistance / 120000)));

    for (let step = 0; step < subdivisions; step += 1) {
      const localT = step / subdivisions;
      const globalT = (distanceSoFar + segmentDistance * localT) / totalDistance;
      smoothed.push(interpolateVisualRoutePoint(current, next, localT, globalT, maxAltitudeMeters));
    }
    distanceSoFar += segmentDistance;
  }

  smoothed.push(points[points.length - 1]);
  return smoothed;
}

function interpolateVisualRoutePoint(
  current: LocationPoint,
  next: LocationPoint,
  localT: number,
  globalT: number,
  maxAltitudeMeters: number
): GeographicPoint {
  const point = interpolateGreatCircle(current, next, localT);
  const currentAltitude = current.altitudeMeters ?? 0;
  const nextAltitude = next.altitudeMeters ?? 0;
  const phase = phaseWeight(globalT);
  const altitudeT = smootherStep(localT);
  const baseAltitude = currentAltitude + (nextAltitude - currentAltitude) * altitudeT;
  const climbDescentLift = Math.sin(Math.PI * phase) * Math.min(4200, maxAltitudeMeters * 0.28);

  return {
    latitude: point.latitude,
    longitude: point.longitude,
    altitudeMeters: Math.max(0, baseAltitude + climbDescentLift)
  };
}

function phaseWeight(globalT: number): number {
  if (globalT < 0.26) {
    return globalT / 0.26;
  }
  if (globalT > 0.74) {
    return (1 - globalT) / 0.26;
  }
  return 0;
}

function smootherStep(value: number): number {
  const t = Math.min(1, Math.max(0, value));
  return t * t * t * (t * (t * 6 - 15) + 10);
}

function remainingRouteFrom(fullRoute: LocationPoint[], flownRoute: LocationPoint[]): LocationPoint[] {
  const current = flownRoute[flownRoute.length - 1];
  if (!current) {
    return fullRoute;
  }
  const currentMs = Date.parse(current.timestamp);
  return [current, ...fullRoute.filter((point) => Date.parse(point.timestamp) > currentMs)];
}

function updatePhaseGroup(
  group: THREE.Group,
  points: LocationPoint[],
  color: number,
  opacity: number,
  altitudeScaleMeters: number
): void {
  for (const child of group.children) {
    if (child instanceof THREE.Line) {
      child.geometry.dispose();
      disposeLineMaterial(child.material);
    }
  }
  group.clear();
  if (points.length < 2) {
    return;
  }
  group.add(createRouteLine(points, { color, opacity, altitudeScaleMeters }));
}

function disposeLineMaterial(material: THREE.Material | THREE.Material[]): void {
  if (Array.isArray(material)) {
    for (const item of material) {
      item.dispose();
    }
    return;
  }
  material.dispose();
}
