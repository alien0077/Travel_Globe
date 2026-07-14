import type { JourneySegment, LocationPoint } from '../data/types';
import {
  EARTH_RADIUS_METERS,
  haversineDistanceMeters,
  initialBearingDegrees,
  toDegrees,
  toRadians
} from '../geo/geodesy';

export type LiveGpsStatus = 'live' | 'estimated' | 'lost';

export interface NativeLocationUpdatePayload {
  timestamp: string;
  latitude: number;
  longitude: number;
  altitudeMeters: number | null;
  speedMetersPerSecond: number | null;
  courseDegrees: number | null;
  horizontalAccuracyMeters: number;
  verticalAccuracyMeters: number | null;
  source: 'gps';
}

export interface NativeBridgeMessage {
  type: string;
  payload: string | NativeLocationUpdatePayload;
}

export interface LiveGpsSample {
  point: LocationPoint;
  bearingDegrees: number;
  distanceFlownMeters: number;
  remainingDistanceMeters: number;
  elapsedSeconds: number;
  status: LiveGpsStatus;
  routePoints: LocationPoint[];
}

const MAX_DEAD_RECKONING_SECONDS = 90;
const MAX_ROUTE_POINTS = 5_000;

export class LiveGpsTracker {
  private readonly routePoints: LocationPoint[] = [];
  private firstReceiptMs?: number;
  private latestReceiptMs?: number;
  private latestRealPoint?: LocationPoint;
  private previousRealPoint?: LocationPoint;
  private latestBearingDegrees?: number;

  ingest(point: LocationPoint, receivedAtMs: number): void {
    if (this.latestRealPoint && Date.parse(point.timestamp) <= Date.parse(this.latestRealPoint.timestamp)) {
      return;
    }

    this.firstReceiptMs = this.firstReceiptMs ?? receivedAtMs;
    this.latestReceiptMs = receivedAtMs;
    this.previousRealPoint = this.latestRealPoint;
    this.latestRealPoint = point;
    this.latestBearingDegrees = resolveBearingDegrees(point, this.previousRealPoint);
    this.routePoints.push(point);
    if (this.routePoints.length > MAX_ROUTE_POINTS) {
      this.routePoints.splice(0, this.routePoints.length - MAX_ROUTE_POINTS);
    }
  }

  sample(nowMs: number, segment: JourneySegment): LiveGpsSample | undefined {
    if (!this.latestRealPoint || this.latestReceiptMs === undefined) {
      return undefined;
    }

    const gapSeconds = Math.max(0, (nowMs - this.latestReceiptMs) / 1000);
    const bearingDegrees = this.latestBearingDegrees ?? 0;
    const hasMotion =
      Number.isFinite(this.latestRealPoint.speedMetersPerSecond) &&
      (this.latestRealPoint.speedMetersPerSecond ?? 0) > 0.5 &&
      Number.isFinite(bearingDegrees);
    const status: LiveGpsStatus =
      gapSeconds <= 1.5 ? 'live' : gapSeconds <= MAX_DEAD_RECKONING_SECONDS && hasMotion ? 'estimated' : 'lost';
    const point =
      status === 'estimated'
        ? estimatePoint(this.latestRealPoint, bearingDegrees, gapSeconds)
        : this.latestRealPoint;
    const routePoints =
      status === 'estimated' ? [...this.routePoints, point] : [...this.routePoints];

    return {
      point,
      bearingDegrees,
      distanceFlownMeters: routeDistanceMeters(routePoints),
      remainingDistanceMeters: haversineDistanceMeters(point, segment.destination),
      elapsedSeconds: this.firstReceiptMs === undefined ? 0 : Math.max(0, (nowMs - this.firstReceiptMs) / 1000),
      status,
      routePoints
    };
  }
}

export function liveGpsPointFromNativeMessage(
  message: unknown,
  journeyId: string,
  segmentId?: string
): LocationPoint | undefined {
  if (!isNativeBridgeMessage(message) || message.type !== 'location.update') {
    return undefined;
  }
  const payload = parseLocationPayload(message.payload);
  if (!payload || !isValidLocationPayload(payload)) {
    return undefined;
  }

  return {
    id: `native-gps-${Date.parse(payload.timestamp)}-${payload.latitude.toFixed(5)}-${payload.longitude.toFixed(5)}`,
    journeyId,
    segmentId,
    timestamp: new Date(payload.timestamp).toISOString(),
    latitude: payload.latitude,
    longitude: payload.longitude,
    altitudeMeters: finiteOrUndefined(payload.altitudeMeters),
    speedMetersPerSecond: finiteOrUndefined(payload.speedMetersPerSecond),
    courseDegrees: normalizeOptionalDegrees(payload.courseDegrees),
    horizontalAccuracyMeters: payload.horizontalAccuracyMeters,
    verticalAccuracyMeters: finiteOrUndefined(payload.verticalAccuracyMeters),
    source: 'gps'
  };
}

function isNativeBridgeMessage(value: unknown): value is NativeBridgeMessage {
  return typeof value === 'object' && value !== null && 'type' in value && 'payload' in value;
}

function parseLocationPayload(payload: NativeBridgeMessage['payload']): NativeLocationUpdatePayload | undefined {
  if (typeof payload === 'string') {
    try {
      return JSON.parse(payload) as NativeLocationUpdatePayload;
    } catch {
      return undefined;
    }
  }
  return payload;
}

function isValidLocationPayload(payload: NativeLocationUpdatePayload): boolean {
  const timestampMs = Date.parse(payload.timestamp);
  return (
    payload.source === 'gps' &&
    Number.isFinite(timestampMs) &&
    Number.isFinite(payload.latitude) &&
    Number.isFinite(payload.longitude) &&
    payload.latitude >= -90 &&
    payload.latitude <= 90 &&
    payload.longitude >= -180 &&
    payload.longitude <= 180 &&
    Number.isFinite(payload.horizontalAccuracyMeters) &&
    payload.horizontalAccuracyMeters >= 0
  );
}

function resolveBearingDegrees(point: LocationPoint, previous?: LocationPoint): number | undefined {
  if (Number.isFinite(point.courseDegrees)) {
    return normalizeDegrees(point.courseDegrees ?? 0);
  }
  if (previous) {
    return initialBearingDegrees(previous, point);
  }
  return undefined;
}

function estimatePoint(point: LocationPoint, bearingDegrees: number, elapsedSeconds: number): LocationPoint {
  const distanceMeters = Math.max(0, (point.speedMetersPerSecond ?? 0) * elapsedSeconds);
  const destination = destinationPoint(point.latitude, point.longitude, bearingDegrees, distanceMeters);
  return {
    ...point,
    id: `${point.id}-estimated`,
    timestamp: new Date(Date.parse(point.timestamp) + elapsedSeconds * 1000).toISOString(),
    latitude: destination.latitude,
    longitude: destination.longitude,
    courseDegrees: bearingDegrees,
    source: 'estimated'
  };
}

function destinationPoint(
  latitude: number,
  longitude: number,
  bearingDegrees: number,
  distanceMeters: number
): { latitude: number; longitude: number } {
  const angularDistance = distanceMeters / EARTH_RADIUS_METERS;
  const bearing = toRadians(bearingDegrees);
  const lat1 = toRadians(latitude);
  const lon1 = toRadians(longitude);
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(angularDistance) +
      Math.cos(lat1) * Math.sin(angularDistance) * Math.cos(bearing)
  );
  const lon2 =
    lon1 +
    Math.atan2(
      Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(lat1),
      Math.cos(angularDistance) - Math.sin(lat1) * Math.sin(lat2)
    );
  return {
    latitude: toDegrees(lat2),
    longitude: normalizeLongitude(toDegrees(lon2))
  };
}

function routeDistanceMeters(points: LocationPoint[]): number {
  return points.reduce((total, point, index) => {
    if (index === 0) {
      return total;
    }
    return total + haversineDistanceMeters(points[index - 1], point);
  }, 0);
}

function finiteOrUndefined(value: number | null): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function normalizeOptionalDegrees(value: number | null): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? normalizeDegrees(value) : undefined;
}

function normalizeDegrees(value: number): number {
  return ((value % 360) + 360) % 360;
}

function normalizeLongitude(longitude: number): number {
  return ((((longitude + 180) % 360) + 360) % 360) - 180;
}
