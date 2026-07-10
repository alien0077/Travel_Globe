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
  constructor(private readonly journey: Journey) {}

  async loadJourney(): Promise<Journey> {
    return this.journey;
  }

  async saveJourney(_journey: Journey): Promise<void> {
    throw new Error('BrowserRuntimeAdapter cannot persist journeys in Phase 1');
  }

  async exportJourney(): Promise<void> {
    throw new Error('Portable export begins after the replay prototype is stable');
  }

  getLocationCapability(): LocationCapability {
    return {
      canRecord: false,
      reason: 'Native recording begins in Phase 3'
    };
  }
}
