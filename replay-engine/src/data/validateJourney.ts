import type { Journey } from './types';

export function assertJourney(value: unknown): asserts value is Journey {
  if (!isObject(value)) {
    throw new Error('Journey payload must be an object');
  }

  const journey = value as Partial<Journey>;
  if (typeof journey.schemaVersion !== 'string' || typeof journey.id !== 'string') {
    throw new Error('Journey payload is missing schemaVersion or id');
  }

  if (!Array.isArray(journey.segments) || journey.segments.length === 0) {
    throw new Error('Journey payload must contain at least one segment');
  }

  for (const segment of journey.segments) {
    if (!isObject(segment)) {
      throw new Error('Journey segment must be an object');
    }
    const route = segment.derivedReplayRoute;
    if (!isObject(route) || !Array.isArray(route.points) || route.points.length < 2) {
      throw new Error('Journey segment must include a derivedReplayRoute with at least two points');
    }
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
