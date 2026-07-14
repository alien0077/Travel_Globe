import type { Journey } from '../data/types';
import { createJsonBlob, createTravelGlobePackage, downloadBlob } from '../export/travelglobePackage';
import { createShareSafeJourney } from '../privacy/redactJourney';

export interface RuntimeAdapter {
  loadJourney(): Promise<Journey>;
  loadJourneyById(journeyId: string): Promise<Journey | undefined>;
  saveJourney(journey: Journey): Promise<void>;
  exportJourney(journey: Journey): Promise<void>;
  exportShareSafeJourney(journey: Journey): Promise<void>;
  getLocationCapability(): LocationCapability;
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

  async saveJourney(journey: Journey): Promise<void> {
    this.journey = journey;
    localStorage.setItem(storageKey(journey.id), JSON.stringify(journey));
    const index = new Set(JSON.parse(localStorage.getItem(indexKey) ?? '[]') as string[]);
    index.add(journey.id);
    localStorage.setItem(indexKey, JSON.stringify([...index]));
    localStorage.setItem(currentJourneyKey, journey.id);
  }

  async exportJourney(journey: Journey): Promise<void> {
    downloadBlob(createTravelGlobePackage(journey), `${journey.id}.travelglobe`);
  }

  async exportShareSafeJourney(journey: Journey): Promise<void> {
    downloadBlob(createJsonBlob(createShareSafeJourney(journey)), `${journey.id}.share-safe.json`);
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
