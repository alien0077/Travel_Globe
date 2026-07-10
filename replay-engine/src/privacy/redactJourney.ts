import type { Journey, LocationPoint } from '../data/types';

export interface RedactionOptions {
  blurEndpointPoints: number;
  removeTimestamps: boolean;
  removeMedia: boolean;
  removeHomeLocation: boolean;
}

export const defaultShareRedaction: RedactionOptions = {
  blurEndpointPoints: 2,
  removeTimestamps: false,
  removeMedia: true,
  removeHomeLocation: true
};

export function createShareSafeJourney(journey: Journey, options = defaultShareRedaction): Journey {
  const copy = structuredClone(journey) as Journey;
  copy.title = `${copy.title} (share-safe)`;

  if (options.removeHomeLocation) {
    delete (copy as Partial<Journey>).homeLocation;
  }

  if (options.removeMedia) {
    copy.media = [];
  }

  for (const segment of copy.segments) {
    for (const route of [segment.rawRoute, segment.processedRoute, segment.derivedReplayRoute]) {
      route.points = route.points.map((point, index, points) =>
        redactPoint(point, shouldBlur(index, points.length, options.blurEndpointPoints), options.removeTimestamps)
      );
    }
  }

  copy.events = copy.events.map((event) => ({
    ...event,
    timestamp: options.removeTimestamps ? '1970-01-01T00:00:00.000Z' : event.timestamp,
    mediaIds: [],
    location: event.location
      ? {
          ...event.location,
          latitude: roundCoordinate(event.location.latitude),
          longitude: roundCoordinate(event.location.longitude)
        }
      : undefined
  }));

  copy.metadata = {
    ...copy.metadata,
    privacyRedacted: true,
    redactedAt: new Date().toISOString()
  };

  return copy;
}

function redactPoint(point: LocationPoint, blur: boolean, removeTimestamp: boolean): LocationPoint {
  return {
    ...point,
    timestamp: removeTimestamp ? '1970-01-01T00:00:00.000Z' : point.timestamp,
    latitude: blur ? roundCoordinate(point.latitude) : point.latitude,
    longitude: blur ? roundCoordinate(point.longitude) : point.longitude,
    horizontalAccuracyMeters: blur
      ? Math.max(point.horizontalAccuracyMeters ?? 0, 5000)
      : point.horizontalAccuracyMeters
  };
}

function shouldBlur(index: number, total: number, endpointPoints: number): boolean {
  return index < endpointPoints || index >= total - endpointPoints;
}

function roundCoordinate(value: number): number {
  return Math.round(value * 20) / 20;
}
