import type { Journey } from '../data/types';

export interface RuntimeAdapter {
  loadJourney(): Promise<Journey>;
  saveJourney(journey: Journey): Promise<void>;
  exportJourney(): Promise<void>;
  getLocationCapability(): LocationCapability;
}

export interface LocationCapability {
  canRecord: boolean;
  reason?: string;
}

export class BrowserRuntimeAdapter implements RuntimeAdapter {
  constructor(private journey: Journey) {}

  async loadJourney(): Promise<Journey> {
    const stored = localStorage.getItem(storageKey(this.journey.id));
    if (!stored) {
      return this.journey;
    }
    this.journey = JSON.parse(stored) as Journey;
    return this.journey;
  }

  async saveJourney(journey: Journey): Promise<void> {
    this.journey = journey;
    localStorage.setItem(storageKey(journey.id), JSON.stringify(journey));
    const index = new Set(JSON.parse(localStorage.getItem(indexKey) ?? '[]') as string[]);
    index.add(journey.id);
    localStorage.setItem(indexKey, JSON.stringify([...index]));
  }

  async exportJourney(): Promise<void> {
    throw new Error('Use createTravelGlobePackage for browser export');
  }

  getLocationCapability(): LocationCapability {
    return {
      canRecord: false,
      reason: 'Native recording begins in Phase 3'
    };
  }
}

const indexKey = 'travel-globe:journey-index';

function storageKey(journeyId: string): string {
  return `travel-globe:journey:${journeyId}`;
}
