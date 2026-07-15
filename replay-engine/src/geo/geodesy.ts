import type { GeographicPoint } from '../data/types';

export const EARTH_RADIUS_METERS = 6371008.8;

export interface Vector3Like {
  x: number;
  y: number;
  z: number;
}

export function toRadians(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

export function toDegrees(radians: number): number {
  return (radians * 180) / Math.PI;
}

export function haversineDistanceMeters(a: GeographicPoint, b: GeographicPoint): number {
  const lat1 = toRadians(a.latitude);
  const lat2 = toRadians(b.latitude);
  const deltaLat = toRadians(b.latitude - a.latitude);
  const deltaLon = toRadians(b.longitude - a.longitude);

  const sinLat = Math.sin(deltaLat / 2);
  const sinLon = Math.sin(deltaLon / 2);
  const h = sinLat * sinLat + Math.cos(lat1) * Math.cos(lat2) * sinLon * sinLon;

  return 2 * EARTH_RADIUS_METERS * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

export function initialBearingDegrees(a: GeographicPoint, b: GeographicPoint): number {
  const lat1 = toRadians(a.latitude);
  const lat2 = toRadians(b.latitude);
  const deltaLon = toRadians(b.longitude - a.longitude);

  const y = Math.sin(deltaLon) * Math.cos(lat2);
  const x =
    Math.cos(lat1) * Math.sin(lat2) -
    Math.sin(lat1) * Math.cos(lat2) * Math.cos(deltaLon);

  return normalizeDegrees(toDegrees(Math.atan2(y, x)));
}

export function interpolateGreatCircle(
  a: GeographicPoint,
  b: GeographicPoint,
  fraction: number
): GeographicPoint {
  const t = clamp(fraction, 0, 1);
  const lat1 = toRadians(a.latitude);
  const lon1 = toRadians(a.longitude);
  const lat2 = toRadians(b.latitude);
  const lon2 = toRadians(b.longitude);

  const angularDistance = haversineDistanceMeters(a, b) / EARTH_RADIUS_METERS;
  if (angularDistance === 0) {
    return {
      latitude: a.latitude,
      longitude: a.longitude,
      altitudeMeters: lerp(a.altitudeMeters ?? 0, b.altitudeMeters ?? 0, t)
    };
  }

  const sinDistance = Math.sin(angularDistance);
  const scaleA = Math.sin((1 - t) * angularDistance) / sinDistance;
  const scaleB = Math.sin(t * angularDistance) / sinDistance;

  const x =
    scaleA * Math.cos(lat1) * Math.cos(lon1) +
    scaleB * Math.cos(lat2) * Math.cos(lon2);
  const y =
    scaleA * Math.cos(lat1) * Math.sin(lon1) +
    scaleB * Math.cos(lat2) * Math.sin(lon2);
  const z = scaleA * Math.sin(lat1) + scaleB * Math.sin(lat2);

  return {
    latitude: toDegrees(Math.atan2(z, Math.sqrt(x * x + y * y))),
    longitude: normalizeLongitude(toDegrees(Math.atan2(y, x))),
    altitudeMeters: lerp(a.altitudeMeters ?? 0, b.altitudeMeters ?? 0, t)
  };
}

export function geographicToVector3(
  point: GeographicPoint,
  radius = 2,
  altitudeScaleMeters = 900000
): Vector3Like {
  const lat = toRadians(point.latitude);
  const lon = toRadians(point.longitude);
  const altitude = point.altitudeMeters ?? 0;
  const displayRadius = altitudeScaleMeters === 0 ? radius : radius + altitude / altitudeScaleMeters;

  return {
    x: displayRadius * Math.cos(lat) * Math.sin(lon),
    y: displayRadius * Math.sin(lat),
    z: displayRadius * Math.cos(lat) * Math.cos(lon)
  };
}

export function formatDistance(meters: number): string {
  if (meters >= 1000) {
    return `${(meters / 1000).toFixed(0)} km`;
  }
  return `${meters.toFixed(0)} m`;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function lerp(a: number, b: number, fraction: number): number {
  return a + (b - a) * fraction;
}

function normalizeLongitude(longitude: number): number {
  return ((((longitude + 180) % 360) + 360) % 360) - 180;
}

function normalizeDegrees(degrees: number): number {
  return ((degrees % 360) + 360) % 360;
}
