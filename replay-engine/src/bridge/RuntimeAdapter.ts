import type { Journey } from '../data/types';
import { exportBlob, type NativeExportDelivery } from './nativeBridge';
import { createJsonBlob, createTravelGlobePackage } from '../export/travelglobePackage';
import { createShareSafeJourney } from '../privacy/redactJourney';

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
    this.journey = JSON.parse(stored) as Journey;
    return this.journey;
  }

  async loadJourneyById(journeyId: string): Promise<Journey | undefined> {
    const stored = localStorage.getItem(storageKey(journeyId));
    if (!stored) {
      return undefined;
    }
    this.journey = JSON.parse(stored) as Journey;
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
      reason: 'Browser replay only; native recording is available in the iOS shell'
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
