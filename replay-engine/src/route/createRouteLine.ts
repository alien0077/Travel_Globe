import * as THREE from 'three';
import type { GeographicPoint, LocationPoint } from '../data/types';
import { geographicToVector3 } from '../geo/geodesy';

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

export function createRouteEventMarkers(points: GeographicPoint[], color = 0xffffff): THREE.Group {
  const group = new THREE.Group();
  const material = new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: 0.35,
    roughness: 0.4
  });

  for (const point of points) {
    const marker = new THREE.Mesh(new THREE.SphereGeometry(0.0035, 12, 8), material);
    const vector = geographicToVector3(point, 2, 620000);
    marker.position.set(vector.x, vector.y, vector.z);
    group.add(marker);
  }

  return group;
}

function createRouteGeometry(points: LocationPoint[], altitudeScaleMeters = 700000): THREE.BufferGeometry {
  const positions: number[] = [];

  for (const point of points) {
    const vector = geographicToVector3(point, 2, altitudeScaleMeters);
    positions.push(vector.x, vector.y, vector.z);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
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
