export type LocationSource = 'gps' | 'estimated' | 'interpolated' | 'imported' | 'planned';

export interface GeographicPoint {
  latitude: number;
  longitude: number;
  altitudeMeters?: number;
}

export interface LocationPoint extends GeographicPoint {
  id: string;
  journeyId: string;
  segmentId?: string;
  timestamp: string;
  speedMetersPerSecond?: number;
  courseDegrees?: number;
  horizontalAccuracyMeters?: number;
  verticalAccuracyMeters?: number;
  source: LocationSource;
}

export interface Route {
  kind: 'raw' | 'processed' | 'derivedReplay' | 'planned';
  points: LocationPoint[];
}

export interface PlaceReference extends GeographicPoint {
  id: string;
  name: string;
  iataCode?: string;
  countryCode?: string;
}

export interface JourneySegment {
  id: string;
  journeyId: string;
  type: 'flight';
  startTime: string;
  endTime: string;
  origin: PlaceReference;
  destination: PlaceReference;
  rawRoute: Route;
  processedRoute: Route;
  derivedReplayRoute: Route;
  events: string[];
  statistics?: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface TimelineEvent {
  id: string;
  journeyId: string;
  segmentId?: string;
  timestamp: string;
  type: string;
  title: string;
  subtitle?: string;
  location?: GeographicPoint;
  mediaIds: string[];
  importance: number;
  source: string;
  metadata: Record<string, unknown>;
}

export interface Journey {
  schemaVersion: string;
  appVersion: string;
  id: string;
  title: string;
  subtitle?: string;
  startTime: string;
  endTime?: string;
  homeLocation?: GeographicPoint;
  status: 'planned' | 'recording' | 'completed' | 'archived';
  plans: unknown[];
  segments: JourneySegment[];
  events: TimelineEvent[];
  media: unknown[];
  journal: unknown[];
  statistics?: Record<string, unknown>;
  settings?: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export function getPrimaryFlightSegment(journey: Journey): JourneySegment {
  const segment = journey.segments.find((candidate) => candidate.type === 'flight');
  if (!segment) {
    throw new Error(`Journey ${journey.id} has no flight segment`);
  }
  return segment;
}
