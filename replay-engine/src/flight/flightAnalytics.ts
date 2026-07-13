import type { GeographicPoint, Journey, JourneySegment, LocationPoint, TimelineEvent } from '../data/types';
import { findNearestLandmark, fixtureLandmarks, type LandmarkProximity } from '../geo/landmarks';
import { haversineDistanceMeters, initialBearingDegrees } from '../geo/geodesy';
import { calculateRouteDistance, getRouteTimeBounds, sampleReplayAt, type ReplaySample } from '../replay/buildReplayFrames';

export type FlightEventKind =
  | 'takeoff'
  | 'topOfClimb'
  | 'cruise'
  | 'topOfDescent'
  | 'landing'
  | 'maxAltitude'
  | 'maxSpeed'
  | 'gpsLost'
  | 'gpsRecovered';

export interface FlightOverlayEvent {
  id: string;
  kind: FlightEventKind;
  title: string;
  timestamp: string;
  point: LocationPoint;
  distanceMeters: number;
}

export interface FlightOverlay {
  flightNumber: string;
  aircraftType: string;
  plannedRoute: LocationPoint[];
  actualRoute: LocationPoint[];
  events: FlightOverlayEvent[];
  totalDistanceMeters: number;
  maxAltitudeMeters: number;
  maxSpeedMetersPerSecond: number;
}

export interface FlightHudMetrics {
  flightNumber: string;
  routeLabel: string;
  altitudeFeet: string;
  speedKmh: string;
  groundSpeedKmh: string;
  headingDegrees: string;
  distanceLabel: string;
  remainingDistanceLabel: string;
  etaLabel: string;
  phaseLabel: string;
  verticalSpeedLabel: string;
}

export interface BelowMeSummary {
  belowLabel: string;
  crossingLabel: string;
  nearby: LandmarkProximity[];
  nextMajorCity?: LandmarkProximity;
}

export function buildFlightOverlay(journey: Journey, segment: JourneySegment): FlightOverlay {
  const plannedRoute = segment.processedRoute.points.length >= 2
    ? segment.processedRoute.points
    : segment.derivedReplayRoute.points;
  const actualRoute = segment.rawRoute.points.length >= 2
    ? segment.rawRoute.points
    : segment.derivedReplayRoute.points;
  const replayRoute = segment.derivedReplayRoute.points;
  const maxAltitudeMeters = Math.max(...replayRoute.map((point) => point.altitudeMeters ?? 0));
  const maxSpeedMetersPerSecond = Math.max(...replayRoute.map((point) => point.speedMetersPerSecond ?? 0));

  return {
    flightNumber: readString(segment.metadata.flightNumber, 'CI100'),
    aircraftType: readString(segment.metadata.aircraftType, ''),
    plannedRoute,
    actualRoute,
    events: detectFlightEvents(journey, segment),
    totalDistanceMeters: calculateRouteDistance(replayRoute),
    maxAltitudeMeters,
    maxSpeedMetersPerSecond
  };
}

export function detectFlightEvents(journey: Journey, segment: JourneySegment): FlightOverlayEvent[] {
  const route = segment.derivedReplayRoute.points;
  const bounds = getRouteTimeBounds(segment);
  const maxAltitudePoint = maxBy(route, (point) => point.altitudeMeters ?? 0);
  const maxSpeedPoint = maxBy(route, (point) => point.speedMetersPerSecond ?? 0);
  const maxAltitudeMeters = maxAltitudePoint.altitudeMeters ?? 0;
  const cruiseThresholdMeters = maxAltitudeMeters * 0.92;
  const takeoffPoint = route.find((point) => (point.altitudeMeters ?? 0) > 600 && (point.speedMetersPerSecond ?? 0) > 35) ?? route[1];
  const topOfClimbPoint = route.find((point) => (point.altitudeMeters ?? 0) >= cruiseThresholdMeters) ?? maxAltitudePoint;
  const topOfDescentPoint =
    [...route].reverse().find((point) => (point.altitudeMeters ?? 0) >= cruiseThresholdMeters) ?? maxAltitudePoint;
  const cruisePoint = route.find((point) => point.timestamp >= topOfClimbPoint.timestamp && point.timestamp <= topOfDescentPoint.timestamp) ?? topOfClimbPoint;
  const landingPoint = route[route.length - 1];

  const generated: FlightOverlayEvent[] = [
    toOverlayEvent('takeoff', 'Takeoff', takeoffPoint, segment, bounds),
    toOverlayEvent('topOfClimb', 'Top of Climb', topOfClimbPoint, segment, bounds),
    toOverlayEvent('cruise', 'Cruise', cruisePoint, segment, bounds),
    toOverlayEvent('topOfDescent', 'Top of Descent', topOfDescentPoint, segment, bounds),
    toOverlayEvent('landing', 'Landing', landingPoint, segment, bounds),
    toOverlayEvent('maxAltitude', 'Max altitude', maxAltitudePoint, segment, bounds),
    toOverlayEvent('maxSpeed', 'Max speed', maxSpeedPoint, segment, bounds)
  ];

  const existing = journey.events
    .filter((event) => event.segmentId === segment.id && event.location)
    .map((event) => eventToOverlayEvent(event, segment, bounds));

  return uniqueEvents([...generated, ...existing]).sort(
    (a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp)
  );
}

export function getActualRouteThrough(segment: JourneySegment, elapsedSeconds: number): LocationPoint[] {
  const route = segment.derivedReplayRoute.points;
  const bounds = getRouteTimeBounds(segment);
  const targetMs = bounds.startMs + Math.min(bounds.durationSeconds, Math.max(0, elapsedSeconds)) * 1000;
  const visible = route.filter((point) => Date.parse(point.timestamp) <= targetMs);
  const samplePoint = interpolateRoutePoint(segment, elapsedSeconds);
  return uniquePoints([...visible, samplePoint]);
}

export function buildFlightHudMetrics(
  journey: Journey,
  segment: JourneySegment,
  sample: ReplaySample,
  elapsedSeconds: number
): FlightHudMetrics {
  const bounds = getRouteTimeBounds(segment);
  const remainingSeconds = Math.max(0, bounds.durationSeconds - elapsedSeconds);
  const flightNumber = readString(segment.metadata.flightNumber, 'CI100');
  const point = sample.point;
  const speedMetersPerSecond = point.speedMetersPerSecond ?? 0;

  return {
    flightNumber,
    routeLabel: `${shortPlace(segment.origin)} -> ${shortPlace(segment.destination)}`,
    altitudeFeet: `${Math.round((point.altitudeMeters ?? 0) * 3.28084).toLocaleString('en-US')} ft`,
    speedKmh: `${Math.round(speedMetersPerSecond * 3.6).toLocaleString('en-US')} km/h`,
    groundSpeedKmh: `${Math.round(speedMetersPerSecond * 3.6).toLocaleString('en-US')} km/h`,
    headingDegrees: `${Math.round(sample.bearingDegrees).toString().padStart(3, '0')} deg`,
    distanceLabel: `${Math.round(sample.distanceFlownMeters / 1000).toLocaleString('en-US')} / ${Math.round(bounds.totalDistanceMeters / 1000).toLocaleString('en-US')} km`,
    remainingDistanceLabel: `${Math.round(sample.remainingDistanceMeters / 1000).toLocaleString('en-US')} km`,
    etaLabel: formatDuration(remainingSeconds),
    phaseLabel: phaseForSample(journey, segment, sample, elapsedSeconds),
    verticalSpeedLabel: verticalSpeedForSample(segment, sample)
  };
}

export function summarizeBelowMe(point: GeographicPoint, headingDegrees: number): BelowMeSummary {
  const nearby = fixtureLandmarks
    .map((feature) => ({
      feature,
      distanceMeters: haversineDistanceMeters(point, feature),
      bearingDegrees: initialBearingDegrees(point, feature),
      relativeWindow: ''
    }))
    .sort((a, b) => a.distanceMeters - b.distanceMeters)
    .slice(0, 4)
    .map((item) => findNearestLandmark(point, headingDegrees, [item.feature]) ?? item);
  const nearest = nearby[0];
  const nextMajorCity = nearby.find((item) => item.feature.type === 'majorCity');

  return {
    belowLabel: inferBelowLabel(point, nearest?.feature.admin1),
    crossingLabel: inferCrossingLabel(point),
    nearby,
    nextMajorCity
  };
}

export function calculateRouteDeviationMeters(sample: ReplaySample, plannedRoute: LocationPoint[]): number {
  if (plannedRoute.length === 0) {
    return 0;
  }
  return Math.min(...plannedRoute.map((point) => haversineDistanceMeters(sample.point, point)));
}

function eventToOverlayEvent(event: TimelineEvent, segment: JourneySegment, bounds: ReturnType<typeof getRouteTimeBounds>): FlightOverlayEvent {
  const location = event.location ?? segment.derivedReplayRoute.points[0];
  const point: LocationPoint = {
    id: event.id,
    journeyId: event.journeyId,
    segmentId: event.segmentId,
    timestamp: event.timestamp,
    latitude: location.latitude,
    longitude: location.longitude,
    altitudeMeters: location.altitudeMeters,
    source: 'estimated'
  };
  return {
    id: event.id,
    kind: normalizeEventKind(event.type),
    title: event.title,
    timestamp: event.timestamp,
    point,
    distanceMeters: distanceAtTimestamp(segment, bounds, event.timestamp)
  };
}

function toOverlayEvent(
  kind: FlightEventKind,
  title: string,
  point: LocationPoint,
  segment: JourneySegment,
  bounds: ReturnType<typeof getRouteTimeBounds>
): FlightOverlayEvent {
  return {
    id: `${segment.id}-${kind}`,
    kind,
    title,
    timestamp: point.timestamp,
    point,
    distanceMeters: distanceAtTimestamp(segment, bounds, point.timestamp)
  };
}

function distanceAtTimestamp(segment: JourneySegment, bounds: ReturnType<typeof getRouteTimeBounds>, timestamp: string): number {
  const elapsedSeconds = (Date.parse(timestamp) - bounds.startMs) / 1000;
  const sample = interpolateRoutePoint(segment, elapsedSeconds);
  const route = segment.derivedReplayRoute.points;
  let distance = 0;
  for (let index = 1; index < route.length; index += 1) {
    if (Date.parse(route[index].timestamp) > Date.parse(sample.timestamp)) {
      return distance + haversineDistanceMeters(route[index - 1], sample);
    }
    distance += haversineDistanceMeters(route[index - 1], route[index]);
  }
  return Math.min(bounds.totalDistanceMeters, distance);
}

function interpolateRoutePoint(segment: JourneySegment, elapsedSeconds: number): LocationPoint {
  return sampleReplayAt(segment, elapsedSeconds).point;
}

function phaseForSample(journey: Journey, segment: JourneySegment, sample: ReplaySample, elapsedSeconds: number): string {
  const events = detectFlightEvents(journey, segment);
  const bounds = getRouteTimeBounds(segment);
  const currentMs = bounds.startMs + elapsedSeconds * 1000;
  const previous = [...events].reverse().find((event) => Date.parse(event.timestamp) <= currentMs);
  if (previous?.kind === 'topOfClimb' || previous?.kind === 'cruise') {
    return 'Cruise';
  }
  if (previous?.kind === 'topOfDescent') {
    return 'Descent';
  }
  if ((sample.point.altitudeMeters ?? 0) < 900 && sample.distanceFlownMeters > 10_000) {
    return 'Approach';
  }
  return previous?.title ?? 'Climb';
}

function verticalSpeedForSample(segment: JourneySegment, sample: ReplaySample): string {
  const route = segment.derivedReplayRoute.points;
  const sampleMs = Date.parse(sample.point.timestamp);
  const nextIndex = route.findIndex((point) => Date.parse(point.timestamp) >= sampleMs);
  const previous = route[Math.max(0, nextIndex - 1)] ?? route[0];
  const next = route[Math.min(route.length - 1, Math.max(1, nextIndex))] ?? route[route.length - 1];
  const minutes = Math.max(1 / 60, (Date.parse(next.timestamp) - Date.parse(previous.timestamp)) / 60000);
  const metersPerMinute = ((next.altitudeMeters ?? 0) - (previous.altitudeMeters ?? 0)) / minutes;
  const rounded = Math.round(metersPerMinute / 10) * 10;
  if (rounded > 30) {
    return `上升 +${rounded.toLocaleString('en-US')} m/min`;
  }
  if (rounded < -30) {
    return `下降 ${rounded.toLocaleString('en-US')} m/min`;
  }
  return '巡航 0 m/min';
}

function normalizeEventKind(type: string): FlightEventKind {
  if (type.includes('TopOfDescent')) {
    return 'topOfDescent';
  }
  if (type.includes('Landing')) {
    return 'landing';
  }
  if (type.includes('Takeoff')) {
    return 'takeoff';
  }
  if (type.includes('Cruise')) {
    return 'cruise';
  }
  return 'cruise';
}

function inferBelowLabel(point: GeographicPoint, admin1?: string): string {
  if (admin1 && point.latitude > 30 && point.longitude > 130) {
    return admin1;
  }
  if (point.latitude > 24 && point.latitude < 32 && point.longitude > 122 && point.longitude < 130) {
    return 'East China Sea';
  }
  if (point.latitude > 32 && point.longitude > 135) {
    return 'Japan FIR';
  }
  if (point.latitude < 26 && point.longitude < 123) {
    return 'Taiwan north coast';
  }
  return admin1 ?? 'Open ocean';
}

function inferCrossingLabel(point: GeographicPoint): string {
  if (point.latitude > 32 && point.longitude > 135) {
    return 'Japan FIR';
  }
  if (point.latitude > 24 && point.longitude > 122 && point.longitude < 134) {
    return 'Pacific / East China Sea corridor';
  }
  return 'Taiwan FIR';
}

function formatDuration(seconds: number): string {
  const totalMinutes = Math.max(0, Math.round(seconds / 60));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = (totalMinutes % 60).toString().padStart(2, '0');
  return `${hours}:${minutes}`;
}

function shortPlace(place: { name: string; iataCode?: string }): string {
  return place.iataCode ?? place.name;
}

function readString(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim().length > 0 ? value : fallback;
}

function maxBy<T>(items: T[], getter: (item: T) => number): T {
  return items.reduce((best, item) => (getter(item) > getter(best) ? item : best));
}

function uniqueEvents(events: FlightOverlayEvent[]): FlightOverlayEvent[] {
  const seen = new Set<string>();
  return events.filter((event) => {
    const key = `${event.kind}-${event.timestamp}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function uniquePoints(points: LocationPoint[]): LocationPoint[] {
  const seen = new Set<string>();
  return points.filter((point) => {
    const key = `${point.timestamp}-${point.latitude.toFixed(5)}-${point.longitude.toFixed(5)}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}
