import type { GeographicPoint } from '../data/types';

export interface PilotViewPerspective {
  altitudeFactor: number;
  eyeForwardOffset: number;
  eyeHeightOffset: number;
  lookAhead: number;
  lookVerticalOffset: number;
  fieldOfViewDegrees: number;
}

export function altitudePerspectiveFactor(pointOrAltitude: GeographicPoint | number | undefined): number {
  const altitudeMeters = typeof pointOrAltitude === 'number'
    ? pointOrAltitude
    : pointOrAltitude?.altitudeMeters ?? 0;
  return smoothstep(1500, 11000, Math.max(0, altitudeMeters));
}

export function pilotViewPerspective(point: GeographicPoint): PilotViewPerspective {
  const altitudeFactor = altitudePerspectiveFactor(point);
  return {
    altitudeFactor,
    eyeForwardOffset: lerp(0.014, 0.042, altitudeFactor),
    eyeHeightOffset: lerp(0.027, 0.058, altitudeFactor),
    lookAhead: lerp(0.64, 2.55, altitudeFactor),
    lookVerticalOffset: lerp(-0.052, -0.24, altitudeFactor),
    fieldOfViewDegrees: lerp(40, 56, altitudeFactor)
  };
}

export function firstPersonRouteLookAheadMeters(point: GeographicPoint): number {
  return lerp(24000, 420000, altitudePerspectiveFactor(point));
}

export function sceneObjectScaleForAltitude(point: GeographicPoint): number {
  return lerp(1.42, 0.58, altitudePerspectiveFactor(point));
}

function smoothstep(edge0: number, edge1: number, value: number): number {
  if (edge0 === edge1) {
    return value < edge0 ? 0 : 1;
  }
  const t = Math.min(1, Math.max(0, (value - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

function lerp(a: number, b: number, fraction: number): number {
  return a + (b - a) * Math.min(1, Math.max(0, fraction));
}
