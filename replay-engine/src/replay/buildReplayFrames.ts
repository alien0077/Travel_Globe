import type { GeographicPoint, JourneySegment, LocationPoint } from '../data/types';
import { haversineDistanceMeters, initialBearingDegrees, interpolateGreatCircle } from '../geo/geodesy';

export interface ReplaySample {
  point: LocationPoint;
  bearingDegrees: number;
  distanceFlownMeters: number;
  remainingDistanceMeters: number;
}

export interface RouteTimeBounds {
  startMs: number;
  endMs: number;
  durationSeconds: number;
  totalDistanceMeters: number;
}

export function getRouteTimeBounds(segment: JourneySegment): RouteTimeBounds {
  const points = getReplayPoints(segment);
  const startMs = Date.parse(points[0].timestamp);
  const endMs = Date.parse(points[points.length - 1].timestamp);

  return {
    startMs,
    endMs,
    durationSeconds: Math.max(1, (endMs - startMs) / 1000),
    totalDistanceMeters: calculateRouteDistance(points)
  };
}

export function sampleReplayAt(segment: JourneySegment, elapsedSeconds: number): ReplaySample {
  const points = getReplayPoints(segment);
  const bounds = getRouteTimeBounds(segment);
  const targetMs = bounds.startMs + Math.min(bounds.durationSeconds, Math.max(0, elapsedSeconds)) * 1000;

  let distanceFlownMeters = 0;

  for (let index = 0; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    const currentMs = Date.parse(current.timestamp);
    const nextMs = Date.parse(next.timestamp);
    const segmentDistance = haversineDistanceMeters(current, next);

    if (targetMs <= nextMs) {
      const fraction = (targetMs - currentMs) / Math.max(1, nextMs - currentMs);
      const interpolated = interpolatePoint(current, next, fraction, targetMs);
      const partialDistance = segmentDistance * Math.min(1, Math.max(0, fraction));

      return {
        point: interpolated,
        bearingDegrees: initialBearingDegrees(current, next),
        distanceFlownMeters: distanceFlownMeters + partialDistance,
        remainingDistanceMeters: Math.max(0, bounds.totalDistanceMeters - distanceFlownMeters - partialDistance)
      };
    }

    distanceFlownMeters += segmentDistance;
  }

  const finalPoint = points[points.length - 1];
  const previousPoint = points[points.length - 2];
  return {
    point: finalPoint,
    bearingDegrees: initialBearingDegrees(previousPoint, finalPoint),
    distanceFlownMeters: bounds.totalDistanceMeters,
    remainingDistanceMeters: 0
  };
}

export function calculateRouteDistance(points: GeographicPoint[]): number {
  return points.reduce((total, point, index) => {
    if (index === 0) {
      return total;
    }
    return total + haversineDistanceMeters(points[index - 1], point);
  }, 0);
}

function getReplayPoints(segment: JourneySegment): LocationPoint[] {
  const points = [...segment.derivedReplayRoute.points].sort(
    (a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp)
  );
  if (points.length < 2) {
    throw new Error(`Segment ${segment.id} needs at least two replay points`);
  }
  return points;
}

function interpolatePoint(
  current: LocationPoint,
  next: LocationPoint,
  fraction: number,
  targetMs: number
): LocationPoint {
  const interpolated = interpolateGreatCircle(current, next, fraction);
  return {
    id: `runtime-${current.id}-${next.id}`,
    journeyId: current.journeyId,
    segmentId: current.segmentId,
    timestamp: new Date(targetMs).toISOString(),
    latitude: interpolated.latitude,
    longitude: interpolated.longitude,
    altitudeMeters: interpolated.altitudeMeters,
    speedMetersPerSecond: lerp(current.speedMetersPerSecond ?? 0, next.speedMetersPerSecond ?? 0, fraction),
    courseDegrees: initialBearingDegrees(current, next),
    source: current.source === 'gps' && next.source === 'gps' ? 'interpolated' : next.source
  };
}

function lerp(a: number, b: number, fraction: number): number {
  return a + (b - a) * Math.min(1, Math.max(0, fraction));
}
