import type { Journey, JourneySegment } from '../data/types';
import { exportBlob, type NativeExportDelivery } from './nativeBridge';
import { createJsonBlob, createTravelGlobePackage } from '../export/travelglobePackage';
import { createShareSafeJourney } from '../privacy/redactJourney';
import {
  buildPreloadedFlightJourney,
  type PreloadFlightRequest,
  type PreloadFlightResult
} from '../flight-preload/buildPreloadedFlightJourney';
import { findRouteShape } from '../flight-preload/routeShapeIndex';

export interface RuntimeAdapter {
  loadJourney(): Promise<Journey>;
  loadJourneyById(journeyId: string): Promise<Journey | undefined>;
  listSavedJourneys(): Promise<SavedJourneySummary[]>;
  saveJourney(journey: Journey): Promise<void>;
  deleteJourney(journeyId: string): Promise<void>;
  exportJourney(journey: Journey): Promise<NativeExportDelivery>;
  exportShareSafeJourney(journey: Journey): Promise<NativeExportDelivery>;
  getLocationCapability(): LocationCapability;
}

export interface SavedJourneySummary {
  id: string;
  title: string;
  status: Journey['status'];
  startTime: string;
  endTime?: string;
}

export interface LocationCapability {
  canRecord: boolean;
  reason?: string;
}

export class BrowserRuntimeAdapter implements RuntimeAdapter {
  constructor(private journey: Journey) {}

  async loadJourney(): Promise<Journey> {
    const currentJourneyId = localStorage.getItem(currentJourneyKey) ?? this.journey.id;
    const stored = localStorage.getItem(storageKey(currentJourneyId));
    if (!stored) {
      return this.journey;
    }
    this.journey = await refreshPlannedRouteFromLatestPack(JSON.parse(stored) as Journey);
    return this.journey;
  }

  async loadJourneyById(journeyId: string): Promise<Journey | undefined> {
    const stored = localStorage.getItem(storageKey(journeyId));
    if (!stored) {
      return undefined;
    }
    this.journey = await refreshPlannedRouteFromLatestPack(JSON.parse(stored) as Journey);
    localStorage.setItem(currentJourneyKey, this.journey.id);
    return this.journey;
  }

  async listSavedJourneys(): Promise<SavedJourneySummary[]> {
    return readJourneyIndex()
      .map((journeyId): SavedJourneySummary | undefined => {
        const stored = localStorage.getItem(storageKey(journeyId));
        if (!stored) {
          return undefined;
        }
        try {
          const journey = JSON.parse(stored) as Journey;
          const summary: SavedJourneySummary = {
            id: journey.id,
            title: journey.title,
            status: journey.status,
            startTime: journey.startTime
          };
          if (journey.endTime) {
            summary.endTime = journey.endTime;
          }
          return summary;
        } catch {
          return undefined;
        }
      })
      .filter((summary): summary is SavedJourneySummary => summary !== undefined)
      .sort((left, right) => Date.parse(right.startTime) - Date.parse(left.startTime));
  }

  async saveJourney(journey: Journey): Promise<void> {
    this.journey = journey;
    localStorage.setItem(storageKey(journey.id), JSON.stringify(journey));
    const index = new Set(readJourneyIndex());
    index.add(journey.id);
    localStorage.setItem(indexKey, JSON.stringify([...index]));
    localStorage.setItem(currentJourneyKey, journey.id);
  }

  async deleteJourney(journeyId: string): Promise<void> {
    localStorage.removeItem(storageKey(journeyId));
    const index = readJourneyIndex().filter((candidate) => candidate !== journeyId);
    localStorage.setItem(indexKey, JSON.stringify(index));
    if (localStorage.getItem(currentJourneyKey) === journeyId) {
      localStorage.removeItem(currentJourneyKey);
    }
  }

  async exportJourney(journey: Journey): Promise<NativeExportDelivery> {
    return exportBlob(createTravelGlobePackage(journey), `${journey.id}.travelglobe`, 'application/x-travelglobe');
  }

  async exportShareSafeJourney(journey: Journey): Promise<NativeExportDelivery> {
    return exportBlob(createJsonBlob(createShareSafeJourney(journey)), `${journey.id}.share-safe.json`, 'application/json');
  }

  getLocationCapability(): LocationCapability {
    return {
      canRecord: false,
      reason: '瀏覽器可使用模擬航線；Live GPS 由 iOS 飛行頁面提供'
    };
  }
}

const indexKey = 'travel-globe:journey-index';
const currentJourneyKey = 'travel-globe:current-journey-id';

function storageKey(journeyId: string): string {
  return `travel-globe:journey:${journeyId}`;
}

function readJourneyIndex(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(indexKey) ?? '[]') as unknown;
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
  } catch {
    return [];
  }
}

async function refreshPlannedRouteFromLatestPack(journey: Journey): Promise<Journey> {
  if (journey.status !== 'planned') {
    return journey;
  }

  const segment = journey.segments.find((candidate) => candidate.type === 'flight');
  const request = segment ? preloadRequestFromJourney(journey, segment) : undefined;
  if (!segment || !request) {
    return journey;
  }

  const routeShape = await findRouteShape(segment.origin, segment.destination).catch(() => undefined);
  if (!routeShape || routeMatches(segment, routeShape)) {
    return journey;
  }

  const rebuilt = buildPreloadedFlightJourney(request, routeShape).journey;
  const rebuiltSegment = rebuilt.segments[0];
  if (!rebuiltSegment) {
    return journey;
  }

  const refreshedSegment: JourneySegment = {
    ...segment,
    rawRoute: rebuiltSegment.rawRoute,
    processedRoute: rebuiltSegment.processedRoute,
    derivedReplayRoute: rebuiltSegment.derivedReplayRoute,
    statistics: rebuiltSegment.statistics,
    metadata: {
      ...segment.metadata,
      ...rebuiltSegment.metadata,
      routeRefresh: 'latest-offline-route-shape-pack'
    }
  };
  const rebuiltEvents = new Map(rebuilt.events.map((event) => [event.id, event]));
  const events = journey.events.map((event) => rebuiltEvents.get(event.id) ?? event);

  return {
    ...journey,
    segments: journey.segments.map((candidate) => candidate.id === segment.id ? refreshedSegment : candidate),
    events,
    statistics: {
      ...journey.statistics,
      ...rebuilt.statistics
    },
    metadata: {
      ...journey.metadata,
      ...rebuilt.metadata,
      routeRefresh: 'latest-offline-route-shape-pack'
    }
  };
}

function preloadRequestFromJourney(journey: Journey, segment: JourneySegment): PreloadFlightRequest | undefined {
  const flightNumber = stringValue(segment.metadata.flightNumber) ?? stringValue(journey.metadata.flightNumber);
  const startMs = Date.parse(segment.startTime);
  const endMs = Date.parse(segment.endTime);
  if (!flightNumber || !segment.origin.iataCode || !segment.destination.iataCode || !Number.isFinite(startMs) || !Number.isFinite(endMs)) {
    return undefined;
  }

  const start = new Date(startMs);
  const dateFromSegmentId = segment.id.match(/(\d{4}-\d{2}-\d{2})$/)?.[1];
  return {
    flightNumber,
    originIata: segment.origin.iataCode,
    destinationIata: segment.destination.iataCode,
    departureDate: dateFromSegmentId ?? formatLocalDate(start),
    departureTime: formatLocalTime(start),
    durationMinutes: Math.max(1, Math.round((endMs - startMs) / 60_000)),
    aircraftType: stringValue(segment.metadata.aircraftType),
    airlineName: stringValue(segment.metadata.airlineName),
    source: preloadSource(segment.metadata.preloadSource)
  };
}

function preloadSource(value: unknown): PreloadFlightResult['source'] | undefined {
  return value === 'offline-airport-index' || value === 'offline-schedule-index' || value === 'aviationstack' || value === 'aviationstack-cache'
    ? value
    : undefined;
}

function routeMatches(segment: JourneySegment, route: Awaited<ReturnType<typeof findRouteShape>>): boolean {
  if (!route || segment.metadata.routeMethod !== route.method || segment.metadata.routeSource !== route.source) {
    return false;
  }
  const points = segment.derivedReplayRoute.points;
  return points.length === route.points.length && points.every((point, index) => {
    const expected = route.points[index];
    return Boolean(expected) && Math.abs(point.latitude - expected.latitude) < 0.0001 && Math.abs(point.longitude - expected.longitude) < 0.0001;
  });
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function formatLocalDate(date: Date): string {
  return [date.getFullYear(), date.getMonth() + 1, date.getDate()]
    .map((part, index) => index === 0 ? String(part).padStart(4, '0') : String(part).padStart(2, '0'))
    .join('-');
}

function formatLocalTime(date: Date): string {
  return [date.getHours(), date.getMinutes()].map((part) => String(part).padStart(2, '0')).join(':');
}
