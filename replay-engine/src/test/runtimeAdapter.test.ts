import { beforeEach, describe, expect, it } from 'vitest';
import { BrowserRuntimeAdapter } from '../bridge/RuntimeAdapter';
import { sampleJourney } from '../data/sampleJourney';
import type { Journey } from '../data/types';

describe('browser runtime adapter journey history', () => {
  beforeEach(() => {
    installMemoryLocalStorage();
  });

  it('lists, loads, and deletes locally saved journeys', async () => {
    const adapter = new BrowserRuntimeAdapter(sampleJourney);
    const olderJourney: Journey = {
      ...sampleJourney,
      id: 'older-journey',
      title: 'Older Journey',
      startTime: '2025-01-01T00:00:00Z'
    };

    await adapter.saveJourney(olderJourney);
    await adapter.saveJourney(sampleJourney);

    const saved = await adapter.listSavedJourneys();
    expect(saved.map((summary) => summary.id)).toEqual([sampleJourney.id, olderJourney.id]);

    const loaded = await adapter.loadJourneyById(olderJourney.id);
    expect(loaded?.title).toBe('Older Journey');

    await adapter.deleteJourney(olderJourney.id);
    expect((await adapter.listSavedJourneys()).map((summary) => summary.id)).toEqual([sampleJourney.id]);
  });
});

function installMemoryLocalStorage(): void {
  const storage = new Map<string, string>();
  Object.defineProperty(globalThis, 'localStorage', {
    value: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear()
    },
    configurable: true
  });
}
